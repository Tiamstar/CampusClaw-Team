# 检查红绿记录

日期为 2026-11-04。

## 原源码红色结果

将个人项目提交 `5fb4aa7af535e5b0be463e8c4e4ad4584098c2af` 导出到独立目录，使用本轮相同的六项边界回归。审计新增的两项测试仅在新源码运行。

```text
Ran 6 tests in 1.260s
FAILED (failures=5, errors=2)
EXIT_CODE=1
```

同一测试中的 JSON 子场景与无写入断言分别产生失败，因此失败条数可超过失败测试方法数。具体触发和返回值见 `security-fix-log.md`。

## 新源码绿色结果

在独立小组数据库上，执行 `python scripts/check.py`。

```text
迁移漂移检查通过
Ran 36 tests in 20.766s
OK
前端 Test Files 2 passed
前端 Tests 20 passed
vite production build succeeded
EXIT_CODE=0
```

另执行 `python scripts/check.py --security`，四组 Python 锁文件审计通过，前端高危及以上为零，密钥扫描通过，退出码为 0。中危开发依赖的书面处置见 `security-baseline.md`。

本轮验证了回归套件能检测原源码缺陷。远端禁止合并仍需仓库管理员将 CI 检查配置为 main 的必需状态。另一位成员的代码交叉评审单独登记。
