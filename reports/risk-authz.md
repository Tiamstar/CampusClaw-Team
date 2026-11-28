# 高风险三查 权限

- 手段。Codex 执行 Django 回归，使用真实签名的教师、同班学生和外部账号 JWT；另在提示生成与工具执行之间撤销成员资格。
- 对象。资料索引任务详情、教师写接口与工具执行授权。第 9 课跨班讲义和检索的完整历史证据见 [安全复测](security-fix-log.md)。
- 判据。任课教师读任务 200 且 GET 不触发模型。同班学生查任务或直接重建为 403，外班身份查任务为 404。撤权后的工具执行拒绝并留下审计。
- 保证与边界。按具体课程 Membership 与角色判定，工具执行前再次取权限。此用例覆盖列出的入口和撤权时点，其他入口对应各自回归。

```sh
docker compose run --rm --no-deps -v "$PWD/backend/core:/app/core:ro" backend python manage.py test core.test_index_tasks.IndexTaskTests.test_authorization_get_is_readonly_and_student_sees_no_task_metadata core.test_baseline_security.ToolReauthorizationTests.test_revocation_between_prompt_and_tool_execution --noinput -v 2
```

2026-11-28 本机结果为该节两个用例均通过。三查与测验截止回归合并执行共 7 项，退出码 0。待队友独立复跑。
