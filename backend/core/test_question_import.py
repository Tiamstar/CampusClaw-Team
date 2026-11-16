from io import BytesIO

from docx import Document
from openpyxl import load_workbook
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Course, KnowledgePoint, Membership, Question, QuestionImportBatch, User
from .question_import import HEADERS, parse_file, template_bytes


class QuestionImportTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('import-teacher@example.test', 'test-password-93')
        self.student = User.objects.create_user('import-student@example.test', 'test-password-93')
        self.course = Course.objects.create(name='Question Import', created_by=self.teacher)
        Membership.objects.create(course=self.course, user=self.teacher, role='teacher')
        Membership.objects.create(course=self.course, user=self.student, role='student')
        self.point = KnowledgePoint.objects.create(course=self.course, name='代数')
        self.tc = APIClient(); self.tc.force_authenticate(self.teacher)
        self.sc = APIClient(); self.sc.force_authenticate(self.student)

    def xlsx(self, rows=(), extra_sheet=False):
        wb = load_workbook(BytesIO(template_bytes('xlsx')))
        ws = wb.active
        ws.delete_rows(2, 1)
        for row in rows: ws.append(row)
        if extra_sheet: wb.create_sheet('unreviewed')
        stream = BytesIO(); wb.save(stream)
        return stream.getvalue()

    def row(self, *, kind='单选', body='解方程 $x=2$', options='1\n2', answer='B', score='5', explanation='逐步求解', points='代数'):
        return [kind, body, options, answer, score, explanation, points]

    def upload(self, raw, name='questions.xlsx', key=None):
        data = {'file': SimpleUploadedFile(name, raw, content_type='application/octet-stream')}
        if key: data['request_key'] = key
        return data

    def test_xlsx_template_round_trips_and_preview_maps_labels(self):
        raw = self.xlsx([self.row()])
        parsed = parse_file('questions.xlsx', raw)
        self.assertEqual(parsed[0]['answer']['values'], ['1'])
        response = self.tc.post(f'/api/courses/{self.course.pk}/questions/import/preview/',
                                self.upload(raw), format='multipart')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['can_import'])
        self.assertEqual(response.data['questions'][0]['points'], ['代数'])
        self.assertEqual(Question.objects.count(), 0)

    def test_docx_template_round_trips_and_maps_boolean_labels(self):
        doc = Document(BytesIO(template_bytes('docx')))
        table = doc.tables[0]
        table._tbl.remove(table.rows[1]._tr)
        row = doc.tables[0].add_row()
        for cell, value in zip(row.cells, self.row(kind='判断', options='', answer='正确', points='')):
            cell.text = value
        stream = BytesIO(); doc.save(stream)
        parsed = parse_file('questions.docx', stream.getvalue())
        self.assertEqual(parsed[0]['answer']['values'], ['true'])
        self.assertEqual(parsed[0]['kind'], 'boolean')

    def test_invalid_row_blocks_entire_atomic_import(self):
        raw = self.xlsx([self.row(), self.row(kind='unknown', body='bad')])
        preview = self.tc.post(f'/api/courses/{self.course.pk}/questions/import/preview/',
                               self.upload(raw), format='multipart')
        self.assertFalse(preview.data['can_import'])
        self.assertEqual(preview.data['errors'][0]['row'], 3)
        committed = self.tc.post(f'/api/courses/{self.course.pk}/questions/import/commit/',
            self.upload(raw, key='stable-import-request-1'), format='multipart')
        self.assertEqual(committed.status_code, 422)
        self.assertEqual(Question.objects.count(), 0)
        self.assertEqual(QuestionImportBatch.objects.count(), 0)

    def test_commit_is_idempotent_and_key_cannot_bind_other_content(self):
        raw = self.xlsx([self.row()]); url=f'/api/courses/{self.course.pk}/questions/import/commit/'
        first = self.tc.post(url, self.upload(raw, key='stable-import-request-2'), format='multipart')
        replay = self.tc.post(url, self.upload(raw, key='stable-import-request-2'), format='multipart')
        self.assertEqual(first.status_code, 201, first.data)
        self.assertFalse(first.data['replayed']); self.assertTrue(replay.data['replayed'])
        self.assertEqual(first.data['question_ids'], replay.data['question_ids'])
        self.assertEqual(Question.objects.count(), 1)
        other = self.tc.post(url, self.upload(self.xlsx([self.row(body='different')]),
            key='stable-import-request-2'), format='multipart')
        self.assertEqual(other.status_code, 409)
        self.assertEqual(Question.objects.count(), 1)

    def test_students_cannot_preview_or_commit_and_wrong_course_points_are_rejected(self):
        raw = self.xlsx([self.row()]); preview_url=f'/api/courses/{self.course.pk}/questions/import/preview/'
        self.assertEqual(self.sc.post(preview_url, self.upload(raw), format='multipart').status_code, 403)
        foreign_course=Course.objects.create(name='Other', created_by=self.teacher)
        KnowledgePoint.objects.create(course=foreign_course, name='Other point')
        foreign_row=self.row(points='Other point')
        response=self.tc.post(preview_url,self.upload(self.xlsx([foreign_row])),format='multipart')
        self.assertFalse(response.data['can_import'])
        self.assertIn('不存在', response.data['errors'][0]['message'])
        commit_url=f'/api/courses/{self.course.pk}/questions/import/commit/'
        self.assertEqual(self.sc.post(commit_url,self.upload(raw,key='stable-import-request-3'),format='multipart').status_code,403)
        self.assertEqual(Question.objects.count(),0)

    def test_rejects_old_extensions_corrupt_files_and_multiple_sheets(self):
        for name, raw in [('questions.xls', b'bad'), ('questions.xlsx', b'not zip'),
                          ('questions.xlsx', self.xlsx([self.row()], extra_sheet=True))]:
            with self.subTest(name=name):
                with self.assertRaises(ValueError): parse_file(name, raw)

    def test_rejects_formulas_hidden_rows_and_merged_cells(self):
        for mutation, expected in [
            (lambda ws: setattr(ws['B2'], 'value', '=1+1'), '公式'),
            (lambda ws: setattr(ws.row_dimensions[2], 'hidden', True), '隐藏'),
            (lambda ws: ws.merge_cells('B2:C2'), '合并'),
        ]:
            with self.subTest(expected=expected):
                wb = load_workbook(BytesIO(self.xlsx([self.row()])))
                mutation(wb.active)
                stream = BytesIO(); wb.save(stream)
                with self.assertRaisesRegex(ValueError, expected):
                    parse_file('questions.xlsx', stream.getvalue())

    def test_template_endpoint_is_authenticated_and_downloadable(self):
        response=self.tc.get('/api/question-import-template/xlsx/')
        self.assertEqual(response.status_code,200)
        self.assertIn('attachment;',response['Content-Disposition'])
        self.assertEqual(self.sc.get('/api/question-import-template/xlsx/').status_code,200)
