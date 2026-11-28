# 高风险三查 并发

- 手段。Codex 执行 Django 回归，两个线程分别打开 PostgreSQL 连接。
- 对象。测验重复开考、并行人工交卷和资料索引重复认领。
- 判据。相同学生的两次开考得到同一答卷，两次交卷均返回 200 并只写一个评分版本。两个索引认领方只有一方成功。依据 QZ-004 和第 8 课重复投递判据。
- 保证与边界。测验以测验行和答卷行协调状态转换。索引以事务内任务行认领协调消费者。两线程规模不能推出系统容量。

```sh
docker compose run --rm --no-deps -v "$PWD/backend/core:/app/core:ro" backend python manage.py test core.test_quiz.QuizConcurrencyTests.test_repeated_start_and_parallel_submit_only_one_grade core.test_index_tasks.IndexTaskTests.test_parallel_claims_do_not_duplicate_execution --noinput -v 2
```

2026-11-28 本机结果为该节两个用例均通过。三查与测验截止回归合并执行共 7 项，退出码 0。待队友独立复跑。
