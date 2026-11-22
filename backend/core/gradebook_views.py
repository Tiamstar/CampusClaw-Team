from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree.ElementTree import Element, SubElement, tostring
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from .forum_views import api_view, access
from .views import fail
from .models import GradePolicy, GradeSnapshot
from .gradebook_service import collect, validate_items, snapshot_data, authorized_grades
from .audit import record_audit


def audit(request, course_id, action, obj):
    record_audit(actor_id=request.user.id, course_id=course_id, action=action,
                 object_ref=str(obj), status='ok', request_id=request.request_id)


@api_view(['GET', 'PUT'])
def policy(request, course_id):
    access(request.user, course_id, True)
    if request.method == 'GET':
        p = GradePolicy.objects.filter(course_id=course_id).first()
        return Response({'revision': p.revision if p else 0, 'items': p.items if p else []})
    try:
        items = validate_items(course_id, request.data.get('items'))
    except ValueError as e:
        return fail(str(e))
    from .models import Course
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=course_id)
        p = GradePolicy.objects.filter(course_id=course_id).first()
        revision = p.revision if p else 0
        if type(request.data.get('expected_revision')) is not int or request.data['expected_revision'] != revision:
            return fail('成绩策略已变化，请刷新', 409)
        p, _ = GradePolicy.objects.update_or_create(course_id=course_id, defaults={'revision': revision + 1, 'items': items})
        audit(request, course_id, 'gradebook.policy', p.id)
    return Response({'revision': p.revision, 'items': p.items})


@api_view(['GET', 'POST'])
def gradebook(request, course_id):
    m = access(request.user, course_id)
    teacher = m.role == 'teacher'
    if request.method == 'POST':
        access(request.user, course_id, True)
        from .models import Course
        with transaction.atomic():
            Course.objects.select_for_update().get(pk=course_id)
            current = collect(course_id)
            if not current['items']:
                return fail('请先保存成绩策略')
            snapshot, created = GradeSnapshot.objects.get_or_create(course_id=course_id, fingerprint=current['fingerprint'],
                defaults={'policy_revision': current['policy_revision'], 'items': current['items'],
                          'rows': current['rows'], 'created_by': request.user})
            audit(request, course_id, 'gradebook.snapshot', snapshot.id)
        return Response(snapshot_data(snapshot, current), status=201 if created else 200)
    return Response(authorized_grades(request.user, course_id))


@api_view(['POST'])
def publication(request, snapshot_id):
    initial = get_object_or_404(GradeSnapshot, pk=snapshot_id)
    access(request.user, initial.course_id, True)
    if type(request.data.get('published')) is not bool:
        return fail('请明确发布或撤回')
    from .models import Course
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=initial.course_id)
        snapshot = GradeSnapshot.objects.select_for_update().get(pk=snapshot_id)
        current = collect(snapshot.course_id)
        if request.data['published']:
            if snapshot.fingerprint != current['fingerprint']:
                return fail('来源或策略已变化，请重新生成快照', 409)
            if not snapshot.rows or any(not r['publishable'] for r in snapshot.rows):
                return fail('存在缺分、待复核或未公开来源，不能发布完整总评', 409)
            snapshot.published_at = snapshot.published_at or timezone.now()
        else:
            snapshot.published_at = None
        snapshot.save(update_fields=['published_at'])
        audit(request, snapshot.course_id, 'gradebook.publication', snapshot.id)
    return Response(snapshot_data(snapshot, current))


def workbook(matrix):
    """Small OOXML workbook: all cells inline strings, so untrusted names cannot be formulas."""
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    sheet = Element('worksheet', xmlns=ns)
    data = SubElement(sheet, 'sheetData')
    for index, values in enumerate(matrix, 1):
        row = SubElement(data, 'row', r=str(index))
        for value in values:
            cell = SubElement(row, 'c', t='inlineStr')
            # XML 1.0 excludes control characters; retain readable user text.
            clean = ''.join(c for c in str(value) if c in '\t\n\r' or 32 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)
            SubElement(SubElement(cell, 'is'), 't').text = clean
    out = BytesIO()
    with ZipFile(out, 'w', ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', '<workbook xmlns="'+ns+'" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="成绩快照" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', tostring(sheet, encoding='utf-8', xml_declaration=True))
    return out.getvalue()


@api_view(['GET'])
def export(request, snapshot_id):
    snapshot = get_object_or_404(GradeSnapshot, pk=snapshot_id)
    access(request.user, snapshot.course_id, True)
    current = collect(snapshot.course_id)
    matrix = [['快照', snapshot.id, '策略版本', snapshot.policy_revision, '生成时间', snapshot.created_at.isoformat(),
               '已过期', snapshot.fingerprint != current['fingerprint']],
              ['指纹', snapshot.fingerprint], ['学号标识', '姓名', '完整', '总评（100分）'] + [f"{i['title']} | {i['weight']}% | {i['selection']}" for i in snapshot.items]]
    for row in snapshot.rows:
        matrix.append([row['student_id'], row['name'], row['complete'], row['total'] if row['total'] is not None else '不完整'] +
                      [f"{v['score']}/{v['max_score']} | {v['status']} | 记录{v['source_record']} | 评分v{v['grade_revision']}" for v in row['entries']])
    response = HttpResponse(workbook(matrix), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="gradebook-{snapshot.id}.xlsx"'
    response['Cache-Control'] = 'no-store'
    audit(request, snapshot.course_id, 'gradebook.export', snapshot.id)
    return response
