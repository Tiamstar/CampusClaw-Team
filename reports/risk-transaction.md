# 高风险三查 事务

- 手段。Codex 执行 Django 回归，在资料上传已插入任务后注入数据库写入异常，在索引重建时注入新向量持久化异常。
- 对象。资料、附件元数据、后台任务和索引状态的事务边界，以及旧索引保护。
- 判据。上传异常后四种业务记录均回滚，媒体目录没有残留文件。同一请求键随后可重新上传并受理为 202，重复处理只执行一次。重建失败保留旧片段并记录失败。
- 保证与边界。上传入口和入队共享 PostgreSQL 事务，异常时显式补偿删除文件。突然终止进程或存储删除本身失败时仍可能遗留文件。处理函数重复调用是可复跑的工程检查，实际停机恢复证据另见 [资料索引交付](../docs/material-index-delivery.md)。

```sh
docker compose run --rm --no-deps -v "$PWD/backend/core:/app/core:ro" backend python manage.py test core.test_index_tasks.IndexTaskTests.test_upload_rolls_back_material_file_and_task_when_enqueue_fails core.test_index_tasks.IndexTaskTests.test_failed_rebuild_keeps_old_chunks_and_atomic_persist_rolls_back --noinput -v 2
```

2026-11-28 本机结果为该节两个用例均通过。三查与测验截止回归合并执行共 7 项，退出码 0。待队友独立复跑。
