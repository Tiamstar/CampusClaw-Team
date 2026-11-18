import json
import httpx
from datetime import timedelta
from unittest.mock import patch, AsyncMock
from django.test import TestCase
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from .models import (User,Course,Membership,ForumPost,ForumReply,ForumDraft,ForumTodo,ForumSettings,
                     KnowledgePoint,Material,StoredFile,KnowledgeEntry,KnowledgeChunk,AuditEvent)
from .forum_service import scan_reminders, verified_citations, generate_draft
from asgiref.sync import async_to_sync


class ForumTests(TestCase):
    def setUp(self):
        self.t=User.objects.create_user('ft@example.test','test-password')
        self.s=User.objects.create_user('fs@example.test','test-password')
        self.peer=User.objects.create_user('fp@example.test','test-password')
        self.out=User.objects.create_user('fo@example.test','test-password')
        self.c=Course.objects.create(name='Forum',created_by=self.t)
        self.other=Course.objects.create(name='Other',created_by=self.out)
        for u,role in [(self.t,'teacher'),(self.s,'student'),(self.peer,'student')]:
            Membership.objects.create(course=self.c,user=u,role=role)
        Membership.objects.create(course=self.other,user=self.out,role='teacher')
        self.tc,self.sc,self.pc,self.oc=[self.client_for(u) for u in [self.t,self.s,self.peer,self.out]]
        self.base=f'/api/courses/{self.c.id}/forum/'
        self.post=ForumPost.objects.create(course=self.c,author=self.s,title='积分问题',body='如何求积分？',anonymous=True)

    def client_for(self,user):
        client=APIClient();client.force_authenticate(user);return client

    def source(self):
        f=StoredFile.objects.create(course=self.c,uploaded_by=self.t,original_name='guide.txt',size=4,kind='material',file='forum-test.txt')
        m=Material.objects.create(course=self.c,title='积分定义',attachment=f)
        e=KnowledgeEntry.objects.create(material=m,status='ready',body_text='积分是累积量')
        chunk=KnowledgeChunk.objects.create(entry=e,chunk_index=0,chunk_text='积分是累积量',status='ready')
        from .agent_runtime import serialize_chunk
        return chunk,verified_citations(self.c.id,[serialize_chunk(chunk,'keyword')])

    def test_anonymity_role_isolation_and_governance(self):
        url=f'/api/forum/posts/{self.post.id}/'
        for client in [self.sc,self.pc]:
            author=client.get(url).data['author'];self.assertEqual(author,{'name':'匿名同学'})
        self.assertEqual(self.tc.get(url).data['author']['id'],self.s.id)
        self.assertEqual(self.oc.get(url).status_code,403)
        self.assertEqual(self.pc.patch(url,{'pinned':True},format='json').status_code,403)
        self.assertEqual(self.tc.patch(url,{'pinned':True,'featured':True},format='json').status_code,200)
        self.assertTrue(AuditEvent.objects.filter(action='forum.moderate',actor_id=self.t.id).exists())
        self.assertEqual(self.sc.post(self.base+'posts/',{'title':'x','body':'x','pinned':True},format='json').status_code,400)

    def test_mentions_points_and_teacher_reply_close_todos(self):
        point=KnowledgePoint.objects.create(course=self.c,name='微积分')
        data={'title':'问题','body':'正文','anonymous':True,'point_ids':[point.id],'mention_ids':[self.t.id]}
        response=self.sc.post(self.base+'posts/',data,format='json');self.assertEqual(response.status_code,201)
        pid=response.data['id'];todo=ForumTodo.objects.get(post_id=pid);self.assertIsNone(todo.closed_at)
        url=f'/api/forum/posts/{pid}/replies/'
        self.assertEqual(self.pc.post(url,{'body':'同学建议'},format='json').status_code,201)
        todo.refresh_from_db();self.assertIsNone(todo.closed_at)
        self.assertEqual(self.tc.post(url,{'body':'教师回答'},format='json').status_code,201)
        todo.refresh_from_db();self.assertIsNotNone(todo.closed_at)
        data['mention_ids']=[self.out.id]
        self.assertEqual(self.sc.post(self.base+'posts/',data,format='json').status_code,400)
        data['mention_ids']=[];data['point_ids']=[KnowledgePoint.objects.create(course=self.other,name='外班').id]
        self.assertEqual(self.sc.post(self.base+'posts/',data,format='json').status_code,400)

    def test_similar_posts_isolation_and_degradation(self):
        ForumPost.objects.create(course=self.other,author=self.out,title='秘密积分问题',body='私密')
        items=self.sc.get(self.base+'similar/?q=积分问题').data['items']
        self.assertEqual([r['id'] for r in items],[self.post.id])
        with patch('core.forum_views.TrigramSimilarity',side_effect=RuntimeError):
            self.assertEqual(self.sc.get(self.base+'similar/?q=积分问题').data['status'],'unavailable')
        self.assertEqual(self.sc.post(self.base+'posts/',{'title':'继续提问','body':'检索失败也能提问'},format='json').status_code,201)

    def test_reminder_scan_dedup_and_closure(self):
        ForumPost.objects.filter(pk=self.post.id).update(created_at=timezone.now()-timedelta(hours=25))
        self.assertEqual(scan_reminders(),1);self.assertEqual(scan_reminders(),0)
        todo=ForumTodo.objects.get(post=self.post,reason='unanswered')
        self.assertEqual(self.sc.get(self.base+'todos/').status_code,403)
        self.tc.post(f'/api/forum/posts/{self.post.id}/replies/',{'body':'已答复'},format='json')
        self.assertEqual(scan_reminders(),0);todo.refresh_from_db();self.assertIsNotNone(todo.closed_at)
        self.assertEqual(ForumTodo.objects.count(),1)

    def test_settings_read_no_write_and_validation(self):
        self.assertEqual(self.sc.get(self.base+'settings/').status_code,200)
        self.assertFalse(ForumSettings.objects.exists())
        data={'draft_enabled':False,'wait_hours':1,'timezone':'Asia/Shanghai','expected_revision':0}
        self.assertEqual(self.sc.put(self.base+'settings/',data,format='json').status_code,403)
        self.assertEqual(self.tc.put(self.base+'settings/',data,format='json').status_code,200)
        self.assertEqual(self.tc.put(self.base+'settings/',data,format='json').status_code,409)
        data.update(expected_revision=1,timezone='Not/AZone')
        self.assertEqual(self.tc.put(self.base+'settings/',data,format='json').status_code,400)
        self.assertEqual(self.sc.post(self.base+'posts/',[],format='json').status_code,400)

    def test_drafts_private_disabled_no_evidence_and_failed(self):
        url=f'/api/forum/posts/{self.post.id}/drafts/'
        self.assertEqual(self.sc.get(url).status_code,403)
        self.assertEqual(self.oc.post(url,{},format='json').status_code,403)
        ForumSettings.objects.create(course=self.c,draft_enabled=False)
        with patch('core.forum_views.generate_draft',new_callable=AsyncMock) as generate:
            self.assertEqual(self.tc.post(url,{},format='json').status_code,409);generate.assert_not_called()
        ForumSettings.objects.filter(course=self.c).update(draft_enabled=True)
        with patch('core.forum_service.search',new_callable=AsyncMock,return_value=[]),patch('core.forum_service.model_stream') as model:
            response=self.tc.post(url,{},format='json');self.assertEqual(response.data['status'],'no_evidence');model.assert_not_called()
        with patch('core.forum_views.generate_draft',new_callable=AsyncMock,side_effect=TimeoutError):
            self.assertEqual(self.tc.post(url,{},format='json').data['status'],'failed')
        self.assertFalse(ForumReply.objects.exists())

    def test_review_publish_idempotency_and_source_revision(self):
        chunk,citations=self.source()
        url=f'/api/forum/posts/{self.post.id}/drafts/'
        with patch('core.forum_views.generate_draft',new_callable=AsyncMock,return_value=('积分是累积量 [资料1]',citations,'test-model')):
            response=self.tc.post(url,{},format='json');self.assertEqual(response.data['status'],'awaiting_review')
        did=response.data['id'];pub=f'/api/forum/drafts/{did}/publish/'
        data={'body':'教师审核：积分表示累积 [资料1]','confirm':True}
        self.assertEqual(self.sc.post(pub,data,format='json').status_code,403)
        self.assertEqual(self.tc.post(pub,{**data,'confirm':False},format='json').status_code,400)
        chunk.chunk_text='资料已更新';chunk.save()
        self.assertEqual(self.tc.post(pub,data,format='json').status_code,409)
        chunk.chunk_text='积分是累积量';chunk.save()
        self.assertEqual(self.tc.post(pub,data,format='json').status_code,201)
        self.assertEqual(self.tc.post(pub,data,format='json').status_code,200)
        self.assertEqual(ForumReply.objects.count(),1)
        public=self.sc.get(f'/api/forum/posts/{self.post.id}/replies/').data['items'][0]
        self.assertEqual(public['confirmed_by'],self.t.id);self.assertEqual(public['citations'][0]['chunk_id'],chunk.id)
        chunk.chunk_text='发布后资料更新';chunk.save()
        public=self.sc.get(f'/api/forum/posts/{self.post.id}/replies/').data['items'][0]
        self.assertFalse(public['citations'][0]['current'])

    def test_late_generation_cannot_override_disabled_settings(self):
        ForumSettings.objects.create(course=self.c)
        async def late(post):
            from asgiref.sync import sync_to_async
            await sync_to_async(lambda:ForumSettings.objects.filter(course=self.c).update(draft_enabled=False,revision=1))()
            return 'late',[],''
        with patch('core.forum_views.generate_draft',side_effect=late):
            response=self.tc.post(f'/api/forum/posts/{self.post.id}/drafts/',{},format='json')
        self.assertEqual(response.data['status'],'failed');self.assertFalse(ForumReply.objects.exists())

    def test_model_rejects_fabricated_source_and_accepts_real_source(self):
        chunk,citations=self.source()
        async def model(messages):
            yield json.dumps({'answer':'有依据 [资料1]','source_ids':[chunk.id]}),'test-model'
        with patch('core.forum_service.search',new_callable=AsyncMock,return_value=citations),patch('core.forum_service.model_stream',side_effect=model):
            result=async_to_sync(generate_draft)(self.post)
        self.assertEqual(result[1][0]['chunk_id'],chunk.id)
        async def bad(messages):
            yield json.dumps({'answer':'捏造','source_ids':[999999]}),'test-model'
        with patch('core.forum_service.search',new_callable=AsyncMock,return_value=citations),patch('core.forum_service.model_stream',side_effect=bad):
            with self.assertRaises(ValueError):async_to_sync(generate_draft)(self.post)

    def test_chinese_phrase_fallback_stays_in_course(self):
        chunk,citations=self.source()
        self.post.title='积分是累积量';self.post.save()
        from .forum_service import phrase_sources
        self.assertEqual([row['chunk_id'] for row in phrase_sources(self.post)],[chunk.id])
        chunk.entry.material.course=self.other;chunk.entry.material.save()
        self.assertEqual(phrase_sources(self.post),[])

    def test_invalid_model_outputs_have_safe_specific_failure_codes(self):
        chunk,citations=self.source()
        cases=[('not-json PRIVATE-MODEL-TEXT','invalid_json'),
               ('[]','invalid_schema'),
               (json.dumps({'answer':42,'source_ids':[chunk.id]}),'invalid_schema'),
               (json.dumps({'answer':'PRIVATE-MODEL-TEXT [资料1]','source_ids':[999999]}),'invalid_source'),
               (json.dumps({'answer':'PRIVATE-MODEL-TEXT [资料99]','source_ids':[chunk.id]}),'citation_labels'),
               ('PRIVATE-MODEL-TEXT'*2000,'output_limit')]
        url=f'/api/forum/posts/{self.post.id}/drafts/'
        from .forum_service import DRAFT_ERRORS
        for raw,code in cases:
            async def model(messages):yield raw,'test-model'
            with self.subTest(code=code),patch('core.forum_service.search',new_callable=AsyncMock,return_value=citations), \
                 patch('core.forum_service.model_stream',side_effect=model),self.assertLogs('campus.audit',level='INFO') as logs:
                response=self.tc.post(url,{},format='json')
            self.assertEqual(response.status_code,201)
            self.assertEqual(response.data['status'],'failed')
            self.assertEqual(response.data['error_code'],code)
            self.assertEqual(response.data['error'],DRAFT_ERRORS[code])
            self.assertEqual(response.data['body'],'')
            self.assertEqual(response.data['citations'],[])
            self.assertNotIn('PRIVATE-MODEL-TEXT',response.content.decode())
            self.assertNotIn('PRIVATE-MODEL-TEXT','\n'.join(logs.output))
            event=AuditEvent.objects.filter(action='forum.draft.failure').latest('id')
            self.assertEqual(event.status,code)
            self.assertEqual(event.object_ref,str(response.data['id']))
            self.assertEqual(event.request_id,response.data['request_id'])
            self.assertEqual(self.sc.get(url).status_code,403)
            self.assertEqual(self.tc.post(f"/api/forum/drafts/{response.data['id']}/publish/",{'confirm':True,'body':'not allowed'},format='json').status_code,409)
        self.assertFalse(ForumReply.objects.exists())

    def test_retrieval_failure_is_distinct_from_model_failure(self):
        with patch('core.forum_service.search',new_callable=AsyncMock,side_effect=RuntimeError('private SQL detail')), \
             patch('core.forum_service.model_stream') as model:
            response=self.tc.post(f'/api/forum/posts/{self.post.id}/drafts/',{},format='json')
        self.assertEqual(response.data['error_code'],'retrieval_error')
        self.assertNotIn('private SQL',response.content.decode());model.assert_not_called()

    def test_transport_timeout_rate_limit_and_unknown_exceptions_are_redacted(self):
        request=httpx.Request('POST','https://private.example.invalid?credential=PRIVATE-CREDENTIAL')
        response=httpx.Response(429,request=request,text='PRIVATE-CREDENTIAL')
        cases=[(TimeoutError('PRIVATE-CREDENTIAL'),'model_timeout'),
               (httpx.ReadTimeout('PRIVATE-CREDENTIAL',request=request),'model_timeout'),
               (httpx.HTTPStatusError('PRIVATE-CREDENTIAL',request=request,response=response),'model_rate_limit'),
               (httpx.ConnectError('PRIVATE-CREDENTIAL',request=request),'model_service'),
               (RuntimeError('PRIVATE-CREDENTIAL'),'internal_error')]
        for exc,code in cases:
            with self.subTest(code=code),patch('core.forum_views.generate_draft',new_callable=AsyncMock,side_effect=exc), \
                 self.assertLogs('campus.audit',level='INFO') as logs:
                result=self.tc.post(f'/api/forum/posts/{self.post.id}/drafts/',{},format='json')
            self.assertEqual(result.data['error_code'],code)
            self.assertNotIn('PRIVATE-CREDENTIAL',result.content.decode())
            self.assertNotIn('PRIVATE-CREDENTIAL','\n'.join(logs.output))
            row=ForumDraft.objects.get(pk=result.data['id'])
            self.assertNotIn('PRIVATE-CREDENTIAL',row.error)

    def test_old_errors_are_not_backfilled_and_interruptions_are_recognizable(self):
        old=ForumDraft.objects.create(post=self.post,requested_by=self.t,status='failed',error='草稿生成失败或已超时，请重试或人工回复')
        running=ForumDraft.objects.create(post=self.post,requested_by=self.t,status='running')
        ForumDraft.objects.filter(pk=running.pk).update(created_at=timezone.now()-timedelta(minutes=6))
        scan_reminders()
        rows=self.tc.get(f'/api/forum/posts/{self.post.id}/drafts/').data['items']
        by_id={r['id']:r for r in rows}
        self.assertEqual(by_id[old.id]['error_code'],'legacy_unknown')
        self.assertEqual(by_id[running.id]['error_code'],'interrupted')
        old.refresh_from_db();self.assertEqual(old.error,'草稿生成失败或已超时，请重试或人工回复')

    def test_permission_loss_does_not_return_generated_private_content(self):
        async def revoke(post):
            from asgiref.sync import sync_to_async
            await sync_to_async(lambda:Membership.objects.filter(course=self.c,user=self.t).delete())()
            return 'private generated text',[],''
        with patch('core.forum_views.generate_draft',side_effect=revoke):
            response=self.tc.post(f'/api/forum/posts/{self.post.id}/drafts/',{},format='json')
        self.assertEqual(response.status_code,403)
        row=ForumDraft.objects.get(post=self.post)
        self.assertEqual(row.body,'')
        from .forum_service import stored_failure_code
        self.assertEqual(stored_failure_code(row),'permission_lost')

    def test_state_change_has_specific_code_without_accepting_late_result(self):
        async def change(post):
            from asgiref.sync import sync_to_async
            await sync_to_async(ForumSettings.objects.filter(course=self.c).update)(draft_enabled=False,revision=1)
            return 'private late output',[],''
        with patch('core.forum_views.generate_draft',side_effect=change):
            response=self.tc.post(f'/api/forum/posts/{self.post.id}/drafts/',{},format='json')
        self.assertEqual(response.data['error_code'],'state_changed')
        self.assertEqual(response.data['body'],'');self.assertFalse(ForumReply.objects.exists())

class ForumResolutionTests(TestCase):
    setUp = ForumTests.setUp
    client_for = ForumTests.client_for
    def test_resolution_permissions_revision_and_reply_scope(self):
        url=f'/api/forum/posts/{self.post.id}/'
        reply=ForumReply.objects.create(post=self.post,author=self.peer,body='建议')
        foreign=ForumPost.objects.create(course=self.other,author=self.out,title='外班',body='外班')
        wrong=ForumReply.objects.create(post=foreign,author=self.out,body='外班答案')
        self.assertEqual(self.pc.patch(url,{'resolved_reply_id':reply.id,'expected_revision':0},format='json').status_code,403)
        self.assertEqual(self.sc.patch(url,{'resolved_reply_id':wrong.id,'expected_revision':0},format='json').status_code,400)
        self.assertEqual(self.sc.patch(url,{'resolved_reply_id':True,'expected_revision':0},format='json').status_code,400)
        self.assertEqual(self.sc.patch(url,{'resolved_reply_id':reply.id,'expected_revision':0},format='json').status_code,200)
        self.post.refresh_from_db();self.assertEqual(self.post.resolved_reply_id,reply.id);self.assertIsNotNone(self.post.resolved_at)
        self.assertEqual(self.tc.patch(url,{'resolved_reply_id':None,'expected_revision':0},format='json').status_code,409)
        self.assertEqual(self.tc.patch(url,{'resolved_reply_id':None,'expected_revision':1},format='json').status_code,200)
        self.post.refresh_from_db();self.assertIsNone(self.post.resolved_reply_id);self.assertIsNone(self.post.resolved_at)
        self.assertEqual(self.oc.get(url).status_code,403)

    def test_reply_search_filters_preserve_counts_anonymity_and_get_readonly(self):
        for _ in range(2):ForumReply.objects.create(post=self.post,author=self.t,body='needle-answer',teacher_answer=True)
        other=ForumPost.objects.create(course=self.other,author=self.out,title='needle-answer',body='hidden')
        before=ForumPost.objects.count()
        rows=self.sc.get(self.base+'posts/?q=needle-answer&status=answered').data['items']
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['reply_count'],2)
        self.assertEqual(rows[0]['author'],{'name':'匿名同学'});self.assertTrue(rows[0]['teacher_answered'])
        self.assertEqual(self.sc.get(self.base+'posts/?status=resolved').data['items'],[])
        self.assertEqual(self.sc.get(self.base+'posts/?status=bad').status_code,400)
        self.assertEqual(ForumPost.objects.count(),before)
        self.assertEqual(self.post.revision,0)

    def test_author_role_and_relevance_search(self):
        exact=ForumPost.objects.create(course=self.c,author=self.t,title='求导',body='教师原帖')
        body=ForumPost.objects.create(course=self.c,author=self.s,title='另外的问题',body='求导',pinned=True)
        reply_only=ForumPost.objects.create(course=self.c,author=self.s,title='回复匹配',body='正文')
        ForumReply.objects.create(post=reply_only,author=self.t,body='求导')
        rows=self.sc.get(self.base+'posts/?q=求导').data['items']
        self.assertEqual([r['id'] for r in rows],[exact.id,body.id,reply_only.id])
        rows=self.sc.get(self.base+'posts/?q=求导&author_role=teacher').data['items']
        self.assertEqual([r['id'] for r in rows],[exact.id])
        self.assertEqual(self.sc.get(self.base+'posts/?author_role=admin').status_code,400)
