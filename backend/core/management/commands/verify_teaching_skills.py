"""Bounded real-provider checks using synthetic teaching examples only."""
import asyncio
import json
import os
from pathlib import Path
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import AgentArtifact, AgentThread, AssistantConfig, Course, Membership, User


CASES = [
    ('lesson-plan-builder', 'lesson', '大学数据库课程，学生已了解 SELECT，50 分钟教学主题为 INNER JOIN 与 LEFT JOIN。请调用已绑定的教案技能，直接在对话中输出可观察的目标、时间分配、练习和离堂检查，不生成文件。'),
    ('socratic-tutor', 'tutor', '我在学复合函数求导，把 (x²+1)² 的导数写成了 2(x²+1)。请先读取已绑定的引导技能，让我自己修正；本轮只给一个诊断问题或很小的提示。'),
    ('misconception-detector', 'exam', '学生说“两个事件互斥，所以一定独立”。请使用错因诊断技能，依据这句话提出待核对的误解，说明如何检验，并给一道不附答案的迁移题。'),
    ('learning-analytics', 'assessment', '匿名练习分数为 12、18、24、30。请先 read_skill，再读取脚本并用 run_skill_script 执行 scripts/summarize_numbers.py，参数为这四个数字。依据真实输出给均值和中位数，并说明学习数据的解释边界。'),
]


class Command(BaseCommand):
    help = 'Run four bounded live teaching-skill checks with disposable synthetic fixtures.'

    def add_arguments(self, parser):
        parser.add_argument('--real', action='store_true')
        parser.add_argument('--output', default='/tmp/teaching-evaluation.json')

    def handle(self, *args, **options):
        if not options['real'] or os.getenv('MODEL_PROVIDER', 'mock') == 'mock':
            raise CommandError('Use --real with a configured real provider')
        user = User.objects.create_user(f'teaching-check-{uuid.uuid4().hex}@example.test', None,
                                        display_name='Synthetic teaching check', can_create_course=True)
        course = Course.objects.create(name='Synthetic teaching evaluation', created_by=user)
        Membership.objects.create(user=user, course=course, role='teacher')
        config = AssistantConfig.objects.create(owner=user, course=course)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + str(RefreshToken.for_user(user).access_token))
        report = {'provider': os.getenv('MODEL_PROVIDER'), 'synthetic_material_only': True, 'cases': []}
        try:
            for skill_id, app_id, prompt in CASES:
                config.app_id, config.skill_ids = app_id, [skill_id]
                config.save()
                thread = AgentThread.objects.create(owner=user, course=course)
                with override_settings(ALLOWED_HOSTS=['testserver']):
                    response = client.post(f'/api/agent/threads/{thread.id}/messages/stream/',
                                           {'content': prompt, 'use_course_materials': False}, format='json')
                    if response.status_code != 200:
                        raise CommandError(f'{skill_id}: HTTP {response.status_code}')
                    async def consume():
                        return b''.join([part async for part in response.streaming_content]).decode()
                    stream = asyncio.run(consume())
                run = thread.runs.latest('id')
                calls = list(run.events.filter(event_type='tool_call').values_list('payload', flat=True))
                results = list(run.events.filter(event_type='tool_result').values_list('payload', flat=True))
                loaded = any(call.get('name') == 'read_skill' and
                             isinstance(call.get('arguments'), dict) and
                             call['arguments'].get('skill_id') == skill_id for call in calls)
                passed = run.status == 'completed' and loaded and 'event: error' not in stream
                tool_failures = [result.get('name') for result in results if result.get('status') != 'ok']
                passed = passed and not tool_failures
                if skill_id == 'learning-analytics':
                    passed = passed and any(result.get('name') == 'run_skill_script' and
                                            result.get('status') == 'ok' and
                                            '21.0' in json.dumps(result.get('result')) for result in results)
                answer = thread.messages.filter(role='assistant').last()
                report['cases'].append({'skill_id': skill_id, 'prompt': prompt, 'status': run.status,
                                        'skill_loaded': loaded, 'tools': [call.get('name') for call in calls],
                                        'passed': passed, 'tool_failures': tool_failures,
                                        'answer_excerpt': answer.content[:3000] if answer else ''})
                self.stdout.write(f'{skill_id}: {run.status}; loaded={loaded}; passed={passed}')
            Path(options['output']).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            if not all(case['passed'] for case in report['cases']):
                raise CommandError('One or more teaching checks failed; inspect the synthetic report')
        finally:
            for artifact in AgentArtifact.objects.filter(course=course):
                artifact.file.delete(save=False)
            course.delete()
            user.delete()
