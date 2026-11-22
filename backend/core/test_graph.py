from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from .models import (User,Course,Membership,StoredFile,Material,KnowledgeEntry,KnowledgeChunk,KnowledgePoint,
                     GraphConfig,GraphCandidate,GraphEdge,GraphResource,GraphVersion,Quiz,QuizAttempt)
from .graph_service import source_rows,validate_proposal


class GraphTests(TestCase):
    def setUp(self):
        self.teacher=User.objects.create_user('graph-t@example.test','test-password')
        self.student=User.objects.create_user('graph-s@example.test','test-password')
        self.course=Course.objects.create(name='Graph',created_by=self.teacher)
        self.other=Course.objects.create(name='Private',created_by=self.teacher)
        for u,r in [(self.teacher,'teacher'),(self.student,'student')]:Membership.objects.create(course=self.course,user=u,role=r)
        self.tc,self.sc=[self.client_for(u) for u in [self.teacher,self.student]]
        self.base=f'/api/courses/{self.course.id}/graph/'
        file=StoredFile.objects.create(course=self.course,uploaded_by=self.teacher,file='graph-fixture.txt',original_name='guide.txt',size=30,kind='material')
        self.material=Material.objects.create(course=self.course,title='积分',attachment=file)
        self.entry=KnowledgeEntry.objects.create(material=self.material,status='ready',content_hash='stable',body_text='函数是定积分的先修知识')
        self.chunk=KnowledgeChunk.objects.create(entry=self.entry,chunk_index=0,status='ready',chunk_text='函数是定积分的先修知识')
        self.sources=source_rows(self.course.id,[self.material.id])
        self.proposal={'nodes':[{'key':'a','name':'函数','source_ids':[self.chunk.id]},{'key':'b','name':'定积分','source_ids':[self.chunk.id]}],
                       'edges':[{'from':'a','to':'b','source_ids':[self.chunk.id]}]}

    def client_for(self,user):
        c=APIClient();c.force_authenticate(user);return c

    def candidate(self,proposal=None):
        return GraphCandidate.objects.create(course=self.course,creator=self.teacher,status='awaiting_review',sources=self.sources,proposal=proposal or self.proposal,settings_revision=0)

    def approve(self,c,proposal=None,rev=0):
        return self.tc.post(f'/api/graph/candidates/{c.id}/review/',{'action':'approve','proposal':proposal or self.proposal,'reason':'逐项回查资料后批准','expected_revision':rev},format='json')

    def test_read_no_writes_roles_and_disabled_no_model(self):
        self.assertEqual(self.tc.get(self.base+'config/').status_code,200)
        self.assertEqual(self.sc.get(self.base).status_code,200)
        self.assertEqual(GraphConfig.objects.count(),0);self.assertEqual(GraphVersion.objects.count(),0)
        for suffix in ['config/','candidates/','versions/']:
            self.assertEqual(self.sc.get(self.base+suffix).status_code,403)
        self.tc.put(self.base+'config/',{'extraction_enabled':False,'expected_revision':0},format='json')
        with patch('core.graph_views.generate') as model:
            r=self.tc.post(self.base+'candidates/',{'material_ids':[self.material.id]},format='json')
            self.assertEqual(r.status_code,409);model.assert_not_called()

    def test_approval_snapshots_sources_and_no_automatic_publication(self):
        with patch('core.graph_views.generate',return_value=(self.proposal,'test-model')):
            response=self.tc.post(self.base+'candidates/',{'material_ids':[self.material.id]},format='json')
        self.assertEqual(response.status_code,201);self.assertEqual(response.data['status'],'awaiting_review')
        self.assertEqual(KnowledgePoint.objects.count(),0)
        item=GraphCandidate.objects.get(pk=response.data['id'])
        self.assertEqual(self.approve(item).status_code,200)
        self.assertEqual(KnowledgePoint.objects.count(),2);self.assertEqual(GraphEdge.objects.count(),1)
        self.assertEqual(GraphResource.objects.count(),2)
        self.assertEqual(GraphVersion.objects.get().snapshot['edges'][0]['sources'][0]['chunk_id'],self.chunk.id)
        self.assertEqual(self.approve(item,rev=1).status_code,409)

    def test_existing_graph_cycle_rejected_without_partial_new_nodes(self):
        self.assertEqual(self.approve(self.candidate()).status_code,200)
        proposal={'nodes':self.proposal['nodes']+[{'key':'c','name':'新节点','source_ids':[self.chunk.id]}],
                  'edges':[{'from':'b','to':'a','source_ids':[self.chunk.id]}]}
        self.assertEqual(self.approve(self.candidate(proposal),proposal,1).status_code,409)
        self.assertFalse(KnowledgePoint.objects.filter(name='新节点').exists())
        self.assertEqual(GraphVersion.objects.count(),1)

    def test_stale_source_and_forged_reference_cannot_be_approved(self):
        item=self.candidate();self.chunk.chunk_text='changed';self.chunk.save()
        self.assertEqual(self.approve(item).status_code,409)
        self.chunk.chunk_text=self.sources[0]['excerpt'];self.chunk.save()
        bad={'nodes':[{'key':'x','name':'假引用','source_ids':[999999]}],'edges':[]}
        self.assertEqual(self.approve(item,bad).status_code,409)
        self.assertEqual(KnowledgePoint.objects.count(),0)
        self.entry.content_hash='new-version';self.entry.save()
        self.assertEqual(self.approve(item).status_code,409)

    def test_model_failure_no_evidence_late_disabled_and_cancelled(self):
        with patch('core.graph_views.generate',side_effect=ValueError('bad')):
            result=self.tc.post(self.base+'candidates/',{'material_ids':[self.material.id]},format='json')
        self.assertEqual(result.data['status'],'failed')
        self.entry.status='pending';self.entry.save()
        with patch('core.graph_views.generate') as model:
            result=self.tc.post(self.base+'candidates/',{'material_ids':[self.material.id]},format='json')
            self.assertEqual(result.data['status'],'no_evidence');model.assert_not_called()
        self.entry.status='ready';self.entry.save()
        async def disable(sources):
            from asgiref.sync import sync_to_async
            await sync_to_async(GraphConfig.objects.create)(course=self.course,extraction_enabled=False,revision=1)
            return self.proposal,'late'
        with patch('core.graph_views.generate',side_effect=disable):
            result=self.tc.post(self.base+'candidates/',{'material_ids':[self.material.id]},format='json')
        self.assertEqual(result.data['status'],'failed');self.assertIn('设置已变化',result.data['error'])
        self.assertEqual(GraphVersion.objects.count(),0)
        running=GraphCandidate.objects.create(course=self.course,creator=self.teacher,settings_revision=1)
        r=self.tc.post(f'/api/graph/candidates/{running.id}/review/',{'action':'cancel','reason':'测试取消'},format='json')
        self.assertEqual(r.data['status'],'cancelled')

    def test_rename_deactivate_keeps_ids_and_rejects_new_associations(self):
        self.approve(self.candidate());point=KnowledgePoint.objects.get(name='定积分')
        old=GraphVersion.objects.get().snapshot
        response=self.tc.put(f'/api/graph/points/{point.id}/',{'name':'定积分新名','active':False,'reason':'保留历史并停用','expected_revision':1},format='json')
        self.assertEqual(response.status_code,200);self.assertEqual(response.data['id'],point.id)
        self.assertEqual(GraphVersion.objects.get(number=1).snapshot,old)
        points=self.sc.get(f'/api/courses/{self.course.id}/forum/points/').data
        self.assertNotIn(point.id,[p['id'] for p in points])
        response=self.sc.post(f'/api/courses/{self.course.id}/forum/posts/',{'title':'问题','body':'正文','point_ids':[point.id]},format='json')
        self.assertEqual(response.status_code,400)

    def test_cross_course_resources_and_private_bank_are_protected(self):
        self.approve(self.candidate());point=KnowledgePoint.objects.get(name='定积分')
        foreign=KnowledgePoint.objects.create(course=self.other,name='secret')
        r=self.tc.post(self.base+'resources/',{'point_id':foreign.id,'material_id':self.material.id,'reason':'bad','expected_revision':1},format='json')
        self.assertEqual(r.status_code,400)
        self.assertEqual(self.sc.get(f'/api/graph/points/{foreign.id}/resources/').status_code,403)
        data=self.sc.get(f'/api/graph/points/{point.id}/resources/').data
        self.assertEqual(data['questions'],[]);self.assertEqual(data['materials'][0]['id'],self.material.id)

    def test_graph_uses_same_scoring_window_and_student_cannot_query_peers(self):
        self.approve(self.candidate());point=KnowledgePoint.objects.get(name='定积分');now=timezone.now()
        quiz=Quiz.objects.create(course=self.course,title='Quiz',status='closed',grades_published=True,opens_at=now-timedelta(days=1),closes_at=now,answers_at=now)
        QuizAttempt.objects.create(quiz=quiz,student=self.student,number=1,status='submitted',submitted_at=now,
            deadline=now,snapshot=[{'id':1,'revision':1,'score':'10','points':[{'id':point.id,'name':'定积分'}]}],
            scores={'1':'6'},grade_revision=1,grading_status='finalized',snapshot_hash='fixture')
        params={'start':(now-timedelta(days=1)).isoformat(),'end':(now+timedelta(days=1)).isoformat()}
        graph=self.sc.get(self.base,params).data
        learning=self.sc.get(f'/api/courses/{self.course.id}/learning/',params).data
        metric=next(n['metric'] for n in graph['nodes'] if n['id']==point.id)
        self.assertEqual(metric,next(p for p in learning['students'][0]['points'] if p['id']==point.id))
        self.assertEqual(graph['learning_version'],learning['data_version'])
        self.assertEqual(self.sc.get(self.base,{**params,'student_id':self.teacher.id}).status_code,403)

    def test_proposal_self_cycle_duplicate_and_limits(self):
        for bad in [None,{'nodes':[],'edges':[{'from':'a','to':'a','source_ids':[self.chunk.id]}]},
                    {'nodes':[self.proposal['nodes'][0]],'edges':[{'from':'a','to':'a','source_ids':[self.chunk.id]}]},
                    {'nodes':[self.proposal['nodes'][0]]*2,'edges':[]}]:
            with self.assertRaises(ValueError):validate_proposal(bad,self.sources)
        self.assertEqual(self.sc.post(self.base+'candidates/',{'material_ids':[self.material.id]},format='json').status_code,403)

    def test_cancelled_late_result_never_restores_pending_candidate(self):
        async def cancel(sources):
            from asgiref.sync import sync_to_async
            await sync_to_async(lambda:GraphCandidate.objects.filter(course=self.course,status='running').update(status='cancelled'))()
            return self.proposal,'late-model'
        with patch('core.graph_views.generate',side_effect=cancel):
            response=self.tc.post(self.base+'candidates/',{'material_ids':[self.material.id]},format='json')
        self.assertEqual(response.status_code,201)
        self.assertEqual(response.data['status'],'cancelled')
        self.assertEqual(response.data['proposal'],{})
        self.assertEqual(GraphVersion.objects.count(),0)

    def test_revoked_teacher_cannot_receive_late_private_sources(self):
        async def revoke(sources):
            from asgiref.sync import sync_to_async
            await sync_to_async(lambda:Membership.objects.filter(course=self.course,user=self.teacher).delete())()
            return self.proposal,'late-model'
        with patch('core.graph_views.generate',side_effect=revoke):
            response=self.tc.post(self.base+'candidates/',{'material_ids':[self.material.id]},format='json')
        self.assertEqual(response.status_code,403)
        self.assertNotIn(self.sources[0]['excerpt'],str(response.data))
        self.assertEqual(GraphCandidate.objects.get().status,'failed')
        self.assertEqual(KnowledgePoint.objects.count(),0)
