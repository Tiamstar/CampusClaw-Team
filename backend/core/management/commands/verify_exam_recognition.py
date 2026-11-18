"""Explicit real-model experiment using synthetic papers, retained for teacher review."""
import json
import os
import uuid
from io import BytesIO
from django.core.management.base import BaseCommand,CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from PIL import Image,ImageDraw,ImageFont
from docx import Document
from docx.shared import Inches
import fitz
from core.models import User,Course,Membership,ExamSource
from core.exam_service import scan_sources


class Command(BaseCommand):
    help='Retain synthetic TXT/image/DOCX/scanned-PDF recognition experiments. Never imports or publishes.'

    def add_arguments(self,parser):
        parser.add_argument('--real',action='store_true')
        parser.add_argument('--teacher-email',required=True)
        parser.add_argument('--course-id',type=int,required=True)
        parser.add_argument('--output',default='/tmp/exam-recognition-evidence.json')
        parser.add_argument('--retry-source-ids',default='')

    def handle(self,*args,**options):
        if not options['real'] or os.getenv('MODEL_PROVIDER','mock')=='mock':raise CommandError('Explicit --real and configured real model required')
        user=User.objects.get(email=options['teacher_email']);course=Course.objects.get(pk=options['course_id'])
        if not Membership.objects.filter(course=course,user=user,role='teacher').exists():raise CommandError('Teacher membership required')
        client=APIClient();client.force_authenticate(user)
        if options['retry_source_ids']:
            for source_id in [int(i) for i in options['retry_source_ids'].split(',')]:
                row=ExamSource.objects.get(pk=source_id,course=course,owner=user)
                response=client.post(f'/api/exam-sources/{row.id}/',{'action':'retry','expected_revision':row.revision},format='json',HTTP_HOST='localhost')
                if response.status_code!=200:raise CommandError('Source not eligible for explicit retry')
                scan_sources(row.id);row.refresh_from_db()
                questions=[q for g in row.draft.get('groups',[]) for q in g['questions']]
                self.stdout.write(json.dumps({'source_id':row.id,'status':row.status,'questions':len(questions),'model':row.model,
                    'missing_answer_keys':sum(not q['answer']['values'] for q in questions),'bank_has_no_score_fields':all('score' not in q for q in questions),
                    'asset_markers':sum(str(g).count('{{asset:') for g in row.draft.get('groups',[])), 'retained':True},ensure_ascii=False))
                if row.status!='ready':raise CommandError('Recognition retry failed; source retained')
            return
        image=Image.new('RGB',(1000,1250),'white');draw=ImageDraw.Draw(image)
        font='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
        title=ImageFont.truetype(font,30);body=ImageFont.truetype(font,24)
        lines=['图文试卷识别验证（合成资料）','共享条件：直角三角形 ABC 中，AB=3，BC=4，∠B=90°。',
               '所有小题共用下图。答案与分值不在试卷中提供。']
        for i,line in enumerate(lines):draw.text((35,35+65*i),line,fill='black',font=title if i==0 else body)
        draw.line([(200,350),(200,650),(600,650),(200,350)],fill='black',width=5)
        for pos,label in [((170,300),'A'),((160,660),'B'),((610,650),'C'),((150,480),'3'),((400,670),'4')]:draw.text(pos,label,fill='black',font=title)
        draw.line([(200,620),(230,620),(230,650)],fill='black',width=3)
        draw.text((35,820),'1. AC 的长度是多少？ A. 3  B. 4  C. 5  D. 7',fill='black',font=body)
        draw.text((35,900),'2. 求三角形 ABC 的面积，并写出计算过程。',fill='black',font=body)
        raw_image=BytesIO();image.save(raw_image,'PNG');png=raw_image.getvalue()
        document=fitz.open();page=document.new_page(width=600,height=750);page.insert_image(page.rect,stream=png);pdf=document.tobytes();document.close()
        doc=Document();doc.add_heading('Reading comprehension: A trip to the park',0)
        doc.add_paragraph('Anna goes to a park every Sunday. She takes a bus at 8:00 and arrives at 8:30. She draws the flowers and returns home at noon. Read the passage and answer both questions.')
        doc.add_paragraph('1. When does Anna arrive? A. 8:00 B. 8:30 C. 12:00')
        doc.add_paragraph('2. What does Anna do in the park? Explain using the passage. No answer key is provided.')
        doc.add_picture(BytesIO(png),width=Inches(5))
        word=BytesIO();doc.save(word)
        text='阅读材料：小林在校园里种下一棵树。每天清晨，他为树浇水，并记录叶片的变化。一个月后，他发现坚持观察比一次测量更能帮助理解生长。\n1. 小林每天做了什么？A.浇水并记录 B.砍树 C.摘花\n2. 结合材料解释持续观察的价值。\n本卷不提供答案与分值。'
        results=[]
        for filename,raw in [('chinese-reading.txt',text.encode('utf-8')),('geometry-photo.png',png),('reading-with-image.docx',word.getvalue()),('geometry-scanned.pdf',pdf)]:
            response=client.post(f'/api/courses/{course.id}/exam-sources/',{'file':SimpleUploadedFile('【识别验收】'+filename,raw),'request_key':uuid.uuid4().hex},format='multipart',HTTP_HOST='localhost')
            if response.status_code!=201:raise CommandError(f'Upload failed: {response.status_code}')
            source_id=response.data['id'];scan_sources(source_id)
            row=ExamSource.objects.get(pk=source_id)
            questions=[q for g in row.draft.get('groups',[]) for q in g['questions']]
            item={'format':filename.rsplit('.',1)[-1],'source_id':source_id,'status':row.status,'units':len(row.units),
                  'groups':len(row.draft.get('groups',[])),'questions':len(questions),'model':row.model,
                  'missing_answer_keys':sum(not q['answer']['values'] for q in questions),
                  'bank_has_no_score_fields':all('score' not in q for q in questions),
                  'asset_markers':sum(str(g).count('{{asset:') for g in row.draft.get('groups',[])),
                  'error':row.error,'semantic_review':'pending_teacher_review','retained':True}
            results.append(item);self.stdout.write(json.dumps(item,ensure_ascii=False))
            with open(options['output'],'w',encoding='utf-8') as f:json.dump({'executor':'Codex','transport':'APIClient server views and real model gateway; not browser or independent acceptance','course_id':course.id,'cases':results},f,ensure_ascii=False,indent=2)
        if any(row['status']!='ready' for row in results):raise CommandError('Some recognition cases failed; evidence and files retained')
