# 导入个人项目作为第一版基座

## Why

用户指定现有个人项目作为小组第一轮迭代。固定可追溯源码和技术栈，复用账号、课程、Agent 与 MCP，并依据第 9、10 课先补请求边界、安全回归和交付检查。

## What Changes

- 导入个人项目提交 `5fb4aa7af535e5b0be463e8c4e4ad4584098c2af` 的已提交源码。
- 修复异常 JSON、GET 触发索引和工具执行时撤权检查。
- 增加审计、请求号、就绪检查、随机本地配置和依赖锁文件。
- 重写实际启动 README，提供统一检查、CI 和两课差距记录。

## Capabilities

### New Capabilities

- `baseline-delivery`：来源、请求与授权边界、独立本地运行和检查结果。

### Modified Capabilities

原三批目标规约继续保留，本轮仅交付基础版。

## Impact

采用 Vue 3、Django、PostgreSQL/pgvector 与 Compose。新增审计表迁移，后续课程公共配置、消息队列、评分与错题按差距清单推进。成员交叉验收结果单独登记。
