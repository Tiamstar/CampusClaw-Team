"""Authenticated stateless MCP Streamable HTTP endpoint for read-only course data.

Uses JSON responses over POST; no server notifications or SSE stream required.
Identity comes from the ordinary JWT authentication layer, never tool arguments.
"""
import json
import time
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
from jsonschema import Draft202012Validator
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.exceptions import APIException, ParseError
from .audit import record_audit
from .forum_views import access
from .models import Quiz
from .quiz_service import quiz_statistics
from .gradebook_service import authorized_grades
from .learning_views import authorized_learning

PROTOCOLS = ('2025-03-26', '2025-06-18', '2025-11-25')
ID = {'type': 'integer', 'minimum': 1}


def schema(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


TOOLS = [
    {'name': 'get_grades', 'description': '读取授权课程成绩册。教师可看来源未公开标记及快照，学生只见本人的已发布有效快照。',
     'inputSchema': schema({'course_id': ID}, ['course_id'])},
    {'name': 'get_quiz_statistics', 'description': '任课教师读取同一正式评分口径的测验统计；学生不能读取班级统计。',
     'inputSchema': schema({'course_id': ID, 'quiz_id': ID}, ['course_id', 'quiz_id'])},
    {'name': 'get_knowledge_mastery', 'description': '读取可解释掌握度与趋势。学生仅本人已公开正式评分；教师可显式查询未公开评分。时间须带时区，窗口不超过366天。',
     'inputSchema': schema({'course_id': ID, 'student_id': ID, 'start': {'type': 'string', 'maxLength': 64},
                           'end': {'type': 'string', 'maxLength': 64}, 'include_unpublished': {'type': 'boolean'}}, ['course_id'])},
]
for tool in TOOLS:
    tool['annotations'] = {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}


def execute(user, name, arguments):
    course_id = arguments['course_id']
    if name == 'get_grades':
        return authorized_grades(user, course_id)
    if name == 'get_quiz_statistics':
        access(user, course_id, True)
        quiz = Quiz.objects.filter(pk=arguments['quiz_id'], course_id=course_id).first()
        if quiz is None:
            raise ValueError('无可见测验')
        result = quiz_statistics(quiz)
        return {**result, 'quiz_id': quiz.id, 'quiz_revision': quiz.revision, 'grades_published': quiz.grades_published}
    params = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in arguments.items() if k != 'course_id'}
    return authorized_learning(user, course_id, params)


def error(rid, code, message, status=200):
    return Response({'jsonrpc': '2.0', 'id': rid, 'error': {'code': code, 'message': message}}, status=status)


@api_view(['POST', 'GET', 'DELETE'])
@parser_classes([JSONParser])
def endpoint(request):
    if request.method != 'POST':
        return HttpResponse(status=405, headers={'Allow': 'POST'})
    if len(request.body) > 65536:
        return error(None, -32600, '请求过大', 413)
    try:
        body = request.data
    except ParseError:
        return error(None, -32700, 'Parse error', 400)
    if not isinstance(body, dict) or body.get('jsonrpc') != '2.0' or not isinstance(body.get('method'), str):
        return error(None, -32600, 'Invalid Request', 400)
    notification = 'id' not in body
    rid = body.get('id')
    if not notification and (type(rid) not in (int, str) or (isinstance(rid, str) and len(rid) > 100)):
        return error(None, -32600, 'Invalid request id', 400)
    method = body['method']
    params = body.get('params', {})
    if not isinstance(params, dict):
        return HttpResponse(status=202) if notification else error(rid, -32602, 'Invalid params')
    protocol = request.headers.get('MCP-Protocol-Version')
    if protocol and protocol not in PROTOCOLS:
        return error(rid, -32600, 'Unsupported protocol version', 400)
    # Notifications never execute tools. This service has no server-side session state.
    if notification:
        return HttpResponse(status=202)
    if method == 'initialize':
        requested = params.get('protocolVersion')
        result = {'protocolVersion': requested if requested in PROTOCOLS else PROTOCOLS[-1],
                  'capabilities': {'tools': {'listChanged': False}},
                  'serverInfo': {'name': 'campus-course-data', 'version': '1.0.0'},
                  'instructions': '只读教学数据工具；每次调用使用当前 Bearer 登录身份再次检查课程权限。'}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        if params.get('cursor'):
            return error(rid, -32602, 'Invalid cursor')
        result = {'tools': TOOLS}
    elif method == 'tools/call':
        tool = next((t for t in TOOLS if t['name'] == params.get('name')), None)
        if tool is None:
            return error(rid, -32602, 'Unknown tool')
        arguments = params.get('arguments', {})
        if not Draft202012Validator(tool['inputSchema']).is_valid(arguments):
            return error(rid, -32602, '工具参数不符合 schema，禁止额外身份、SQL 或 URL 参数')
        started = time.monotonic()
        status = 'ok'
        try:
            data = execute(request.user, tool['name'], arguments)
            # MCP JSON includes no Python datetime/Decimal values.
            data = json.loads(json.dumps(data, cls=DjangoJSONEncoder, ensure_ascii=False))
            result = {'content': [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False)}],
                      'structuredContent': data, 'isError': False}
        except (APIException, ValueError) as exc:
            status = 'denied' if isinstance(exc, APIException) and exc.status_code in (403, 404) else 'invalid'
            result = {'content': [{'type': 'text', 'text': '无权查询此数据' if status == 'denied' else str(exc)}], 'isError': True}
        finally:
            record_audit(actor_id=request.user.id, course_id=arguments['course_id'], action='mcp.'+tool['name'],
                         object_ref=tool['name'], status=status, request_id=request.request_id,
                         duration_ms=round((time.monotonic()-started)*1000))
    else:
        return error(rid, -32601, 'Method not found')
    return Response({'jsonrpc': '2.0', 'id': rid, 'result': result})
