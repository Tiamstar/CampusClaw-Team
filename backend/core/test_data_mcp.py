from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, Course, Membership, AuditEvent, GradePolicy, GradeSnapshot


class CourseMCPTests(TestCase):
    def setUp(self):
        self.teacher=User.objects.create_user('mcp-teacher@example.test','test-password')
        self.student=User.objects.create_user('mcp-student@example.test','test-password')
        self.peer=User.objects.create_user('mcp-peer@example.test','test-password')
        self.course=Course.objects.create(name='MCP',created_by=self.teacher)
        for user,role in [(self.teacher,'teacher'),(self.student,'student'),(self.peer,'student')]:
            Membership.objects.create(course=self.course,user=user,role=role)
        self.tc,self.sc=[self.client_for(u) for u in [self.teacher,self.student]]
        self.path='/api/mcp/course-data/'

    def client_for(self,user):
        client=APIClient();client.credentials(HTTP_AUTHORIZATION='Bearer '+str(RefreshToken.for_user(user).access_token));return client

    def rpc(self,client,method,params=None,**headers):
        return client.post(self.path,{'jsonrpc':'2.0','id':7,'method':method,'params':params or {}},format='json',**headers)

    def call(self,client,name,args):
        return self.rpc(client,'tools/call',{'name':name,'arguments':args})

    def test_initialize_list_and_notification_stateless_protocol(self):
        for version in ['2025-03-26','2025-06-18','2025-11-25']:
            response=self.rpc(self.tc,'initialize',{'protocolVersion':version,'capabilities':{},'clientInfo':{'name':'test','version':'1'}})
            self.assertEqual(response.data['result']['protocolVersion'],version)
        notification=self.tc.post(self.path,{'jsonrpc':'2.0','method':'notifications/initialized'},format='json')
        self.assertEqual(notification.status_code,202)
        tools=self.rpc(self.tc,'tools/list').data['result']['tools']
        self.assertEqual({t['name'] for t in tools},{'get_grades','get_quiz_statistics','get_knowledge_mastery'})
        self.assertTrue(all(t['annotations']['readOnlyHint'] for t in tools))
        self.assertEqual(self.tc.get(self.path).status_code,405)
        self.assertEqual(self.rpc(self.tc,'ping').data['result'],{})
        self.assertEqual(self.rpc(self.tc,'resources/list').data['error']['code'],-32601)

    def test_bearer_required_and_identity_never_accepted_from_model(self):
        self.assertEqual(APIClient().post(self.path,{},format='json').status_code,401)
        for args in [{'course_id':self.course.id,'student_id':self.peer.id},
                     {'course_id':self.course.id,'role':'teacher'},
                     {'course_id':self.course.id,'sql':'select * from core_user'},
                     {'course_id':True},{'course_id':self.course.id,'url':'http://private'}]:
            self.assertEqual(self.call(self.sc,'get_grades',args).data['error']['code'],-32602)
        denied=self.call(self.sc,'get_knowledge_mastery',{'course_id':self.course.id,'student_id':self.peer.id})
        self.assertTrue(denied.data['result']['isError'])
        unpublished=self.call(self.sc,'get_knowledge_mastery',{'course_id':self.course.id,'include_unpublished':True})
        self.assertTrue(unpublished.data['result']['isError'])
        self.assertNotIn(self.peer.email,str(denied.data))

    def test_results_equal_pages_and_no_business_writes(self):
        from .gradebook_service import authorized_grades
        response=self.call(self.sc,'get_grades',{'course_id':self.course.id})
        self.assertEqual(response.data['result']['structuredContent'],authorized_grades(self.student,self.course.id))
        args={'course_id':self.course.id,'start':'2026-11-01T00:00:00Z','end':'2026-11-15T00:00:00Z'}
        mcp=self.call(self.sc,'get_knowledge_mastery',args).data['result']['structuredContent']
        page=self.sc.get(f'/api/courses/{self.course.id}/learning/',{k:v for k,v in args.items() if k!='course_id'}).data
        self.assertEqual(mcp,page)
        self.assertEqual([s['student_id'] for s in mcp['students']],[self.student.id])
        self.assertEqual(GradePolicy.objects.count(),0);self.assertEqual(GradeSnapshot.objects.count(),0)
        self.assertTrue(AuditEvent.objects.filter(actor_id=self.student.id,action='mcp.get_knowledge_mastery',status='ok').exists())

    def test_execution_rechecks_membership_and_stats_teacher_only(self):
        self.rpc(self.tc,'tools/list')
        Membership.objects.filter(course=self.course,user=self.teacher).delete()
        self.assertTrue(self.call(self.tc,'get_grades',{'course_id':self.course.id}).data['result']['isError'])
        stats=self.call(self.sc,'get_quiz_statistics',{'course_id':self.course.id,'quiz_id':1})
        self.assertTrue(stats.data['result']['isError'])
        other=Course.objects.create(name='Other',created_by=self.teacher)
        self.assertTrue(self.call(self.sc,'get_grades',{'course_id':other.id}).data['result']['isError'])

    def test_malformed_params_and_notification_do_not_execute(self):
        with patch('core.data_mcp.execute') as execute:
            response=self.sc.post(self.path,{'jsonrpc':'2.0','method':'tools/call','params':{'name':'get_grades','arguments':{'course_id':self.course.id}}},format='json')
            self.assertEqual(response.status_code,202);execute.assert_not_called()
        for payload in [[],{}, {'jsonrpc':'2.0','id':None,'method':'ping'}, {'jsonrpc':'2.0','id':True,'method':'ping'}]:
            self.assertEqual(self.sc.post(self.path,payload,format='json').status_code,400)
        self.assertEqual(self.sc.post(self.path,'{broken',content_type='application/json').data['error']['code'],-32700)
        self.assertEqual(self.rpc(self.sc,'tools/list',HTTP_MCP_PROTOCOL_VERSION='old').status_code,400)
        self.assertEqual(self.call(self.sc,'unknown',{}).data['error']['code'],-32602)
