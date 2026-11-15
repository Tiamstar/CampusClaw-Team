"""Retained synthetic load-test fixtures; private tokens never enter reports."""
import hashlib
import json
import random
import string
from datetime import timedelta
from pathlib import Path
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken
from core.models import User, Course, Membership, Assignment, Submission, SubmissionVersion, StoredFile, Material, KnowledgeEntry, KnowledgeChunk
from core.assignment_views import submission_hash


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--teacher', required=True)
        parser.add_argument('--student', required=True)
        parser.add_argument('--output', default='/tmp/benchmark-private.json')
        parser.add_argument('--chunks', type=int, default=10000)

    def handle(self, *args, **options):
        teacher=User.objects.get(email=options['teacher'],is_active=True)
        student=User.objects.get(email=options['student'],is_active=True)
        if not teacher.can_create_course or teacher==student or not 100<=options['chunks']<=20000:
            raise CommandError('Invalid selected accounts or fixture size')
        course=Course.objects.create(name='CampusClaw 性能验收（合成资料与提交保留）',created_by=teacher)
        Membership.objects.create(course=course,user=teacher,role='teacher')
        Membership.objects.create(course=course,user=student,role='student')
        query=Assignment.objects.create(course=course,title='【性能验收】固定20版本查询样本',
            description='合成样本，查询压测不改动；不代表20名学生。',max_score=10,due_at=timezone.now()+timedelta(days=90))
        submission=Submission.objects.create(assignment=query,student=student)
        for i in range(20):
            text=f'性能验收固定历史版本{i+1}：积分结果为1。'
            SubmissionVersion.objects.create(submission=submission,number=i+1,text_content=text,
                submission_key=f'fixture-{i+1}',content_hash=submission_hash(text,[]))
        submit=Assignment.objects.create(course=course,title='【性能验收】并发文字提交（不评分）',
            description='k6真实201提交与幂等200重放均保留。单一学生账号20虚拟客户端，每次提交使用独立键，不调用AI。',
            max_score=10,due_at=timezone.now()+timedelta(days=90))
        rng=random.Random(20261116)
        texts=['benchmarkneedle benchmarkneedle benchmarkneedle']
        texts += [' '.join(''.join(rng.choices(string.ascii_lowercase,k=8)) for _ in range(30)) for _ in range(options['chunks']-1)]
        body='\n\n'.join(texts)
        stored=StoredFile.objects.create(course=course,uploaded_by=teacher,kind='material',original_name='synthetic-benchmark.txt',size=len(body.encode()))
        stored.file.save('synthetic-benchmark.txt',ContentFile(body.encode()),save=True)
        material=Material.objects.create(course=course,title='【性能合成】固定随机词法检索语料',attachment=stored)
        entry=KnowledgeEntry.objects.create(material=material,body_text=body,parser='txt',status='ready',
            content_hash=hashlib.sha256(body.encode()).hexdigest(),indexed_at=timezone.now())
        offset=0; chunks=[]
        for i,text in enumerate(texts):
            chunks.append(KnowledgeChunk(entry=entry,chunk_index=i,chunk_text=text,start_offset=offset,end_offset=offset+len(text),status='ready'))
            offset+=len(text)+2
        KnowledgeChunk.objects.bulk_create(chunks,batch_size=500)
        token=AccessToken.for_user(student);token.set_exp(lifetime=timedelta(hours=8))
        Path(options['output']).write_text(json.dumps({'token':str(token),'course_id':course.pk,
            'query_assignment_id':query.pk,'submit_assignment_id':submit.pk,'query':'benchmarkneedle'}),encoding='utf-8')
        self.stdout.write(json.dumps({'course_id':course.pk,'query_assignment_id':query.pk,'submit_assignment_id':submit.pk,
            'material_id':material.pk,'chunks':len(chunks),'body_sha256':entry.content_hash,'join_code':course.join_code}))
