"""MCP never runs before explicit, current, single-use authorization."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import AsyncMock, patch
from asgiref.sync import async_to_sync
from django.db import close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, Course, Membership, AgentThread, CourseAssistantConfig, MCPServer, ToolConfirmation, AgentRun, AuditEvent


class ConfirmationTests(TransactionTestCase):
    def client_for(self,user):
        client=APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer '+str(RefreshToken.for_user(user).access_token))
        return client

    def setUp(self):
        self.user=User.objects.create_user('confirmation@example.test','test-password',can_create_course=True)
        self.other=User.objects.create_user('confirmation-other@example.test','test-password')
        self.course=Course.objects.create(name='Confirmation fixture',created_by=self.user)
        Membership.objects.create(course=self.course,user=self.user,role='teacher')
        Membership.objects.create(course=self.course,user=self.other,role='student')
        self.thread=AgentThread.objects.create(owner=self.user,course=self.course)
        self.server=MCPServer.objects.create(owner=self.user,name='shared',url='http://campus-tools:8100/mcp',
            token_env='MCP_CAMPUS_TOKEN',connected=True,is_shared=True,
            tools=[{'name':'hint','description':'fixture','inputSchema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text'],'additionalProperties':False}}])
        self.config=CourseAssistantConfig.objects.create(course=self.course,edited_by=self.user,mcp_refs=['hint@shared'])
        self.client=self.client_for(self.user)
        self.base=f'/api/agent/threads/{self.thread.pk}/'
        self.tool=f'mcp_{self.server.pk}_hint'

    def pending(self,text='private argument'):
        with patch('core.skill_runtime.rpc',new=AsyncMock()) as rpc:
            response=self.client.post(self.base+'tool-test/',{'name':self.tool,'arguments':{'text':text}},format='json')
            self.assertEqual(response.status_code,200,response.content)
            self.assertEqual(response.json()['status'],'pending')
            rpc.assert_not_called()
        return ToolConfirmation.objects.get(pk=response.json()['result']['confirmation_id'])

    def act(self,row,action='confirm',client=None,**extra):
        return (client or self.client).post(self.base+f'confirmations/{row.pk}/',{'action':action,**extra},format='json')

    def test_pending_get_readonly_private_and_exact_execution_once(self):
        row=self.pending()
        self.assertEqual(self.pending().pk,row.pk)
        before=ToolConfirmation.objects.count()
        self.assertEqual(self.client.get(self.base+'confirmations/').json()[0]['arguments'],row.arguments)
        self.assertEqual(ToolConfirmation.objects.count(),before)
        self.assertEqual(self.client_for(self.other).get(self.base+'confirmations/').status_code,404)
        self.assertEqual(self.act(row,client=self.client_for(self.other)).status_code,404)
        self.assertEqual(self.act(row,arguments={'text':'override'}).status_code,400)
        with patch('core.skill_runtime.rpc',new=AsyncMock(return_value=({'content':[{'type':'text','text':'42'}]},''))) as rpc:
            result=self.act(row)
            self.assertEqual(result.status_code,200,result.content)
            self.assertEqual(result.json()['status'],'succeeded')
            self.assertEqual(rpc.call_args.args[2]['arguments'],row.arguments)
            self.assertEqual(self.act(row).status_code,409)
            self.assertEqual(rpc.call_count,1)
        # Audit contains metadata only; the private confirmation is not course-visible audit data.
        self.assertNotIn('private argument',json.dumps(list(AuditEvent.objects.values()),default=str))
        self.assertTrue(AuditEvent.objects.filter(action='tool.invoke',status='pending').exists())

    def test_reject_expire_and_wrong_thread_never_execute(self):
        row=self.pending()
        self.assertEqual(self.act(row,'reject').json()['status'],'rejected')
        expired=self.pending('expires')
        ToolConfirmation.objects.filter(pk=expired.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        thread=AgentThread.objects.create(owner=self.user,course=self.course)
        with patch('core.skill_runtime.rpc',new=AsyncMock()) as rpc:
            self.assertEqual(self.act(row).status_code,409)
            self.assertEqual(self.act(expired).status_code,409)
            self.assertEqual(self.client.get(self.base+'confirmations/').json()[0]['status'],'expired')
            self.assertEqual(self.client.post(f'/api/agent/threads/{thread.pk}/confirmations/{expired.pk}/',{'action':'confirm'},format='json').status_code,404)
            rpc.assert_not_called()

    def test_changed_bindings_config_parameters_and_membership_block(self):
        for change in ['url','schema','description','disconnected','unshared','unbound','revision','arguments','membership']:
            with self.subTest(change=change):
                row=self.pending(change)
                original_tools=json.loads(json.dumps(self.server.tools))
                if change=='url':self.server.url='http://campus-tools:8100/other'
                elif change=='schema':self.server.tools[0]['inputSchema']['properties']['text']['maxLength']=100
                elif change=='description':self.server.tools[0]['description']='changed'
                elif change=='disconnected':self.server.connected=False
                elif change=='unshared':self.server.is_shared=False
                elif change=='unbound':self.config.mcp_refs=[]
                elif change=='revision':self.config.revision+=1
                elif change=='arguments':ToolConfirmation.objects.filter(pk=row.pk).update(arguments={'text':'tampered'})
                elif change=='membership':Membership.objects.filter(user=self.user,course=self.course).delete()
                self.server.save();self.config.save()
                with patch('core.skill_runtime.rpc',new=AsyncMock()) as rpc:
                    self.assertIn(self.act(row).status_code,[404,409])
                    rpc.assert_not_called()
                self.server.url='http://campus-tools:8100/mcp';self.server.tools=original_tools
                self.server.connected=True;self.server.is_shared=True;self.server.save()
                self.config.mcp_refs=['hint@shared'];self.config.save()
                Membership.objects.get_or_create(user=self.user,course=self.course,defaults={'role':'teacher'})

    def test_remote_error_and_timeout_are_terminal_and_honest(self):
        for result in [{'isError':True,'content':[{'type':'text','text':'fixture failure'}]},TimeoutError()]:
            row=self.pending(str(result))
            mock=AsyncMock(side_effect=result) if isinstance(result,Exception) else AsyncMock(return_value=(result,''))
            with patch('core.skill_runtime.rpc',new=mock):
                response=self.act(row)
                self.assertIn(response.status_code,[200,409])
                row.refresh_from_db();self.assertEqual(row.status,'failed')
                self.assertEqual(self.act(row).status_code,409)
                self.assertEqual(mock.call_count,1)
        self.assertFalse(self.thread.messages.filter(content__contains='工具调用完成').exists())

    def test_two_concurrent_confirmations_only_one_rpc_attempt(self):
        row=self.pending();barrier=Barrier(2)
        def confirm():
            close_old_connections()
            try:
                client=self.client_for(self.user);barrier.wait(timeout=10)
                return self.act(row,client=client).status_code
            finally:close_old_connections()
        with patch('core.skill_runtime.rpc',new=AsyncMock(return_value=({'content':[]},''))) as rpc:
            with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(lambda _:confirm(),range(2)))
            self.assertEqual(sorted(statuses),[200,409])
            self.assertEqual(rpc.call_count,1)

    def test_model_stream_pauses_after_first_pending_call_without_second_round(self):
        calls=[]
        async def model(*args):
            calls.append(1)
            yield {'tool_calls':[{'id':'a','type':'function','function':{'name':self.tool,'arguments':json.dumps({'text':'stream'})}},
                                 {'id':'b','type':'function','function':{'name':self.tool,'arguments':json.dumps({'text':'second'})}}]},'fixture'
        with patch('core.agent_views.model_stream',model),patch('core.skill_runtime.rpc',new=AsyncMock()) as rpc:
            response=self.client.post(self.base+'messages/stream/',{'content':'use MCP'},format='json')
            async def consume():return b''.join([part async for part in response.streaming_content]).decode()
            body=asyncio.run(consume())
            self.assertIn('event: message_end',body)
            self.assertIn('confirmation_required',body)
            self.assertEqual(len(calls),1)
            self.assertEqual(ToolConfirmation.objects.count(),1)
            self.assertEqual(AgentRun.objects.get(thread=self.thread).events.get(event_type='tool_result').payload['status'],'pending')
            rpc.assert_not_called()
