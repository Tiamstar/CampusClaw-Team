# v0.1.0 基础版交付说明

日期为 2026-11-04。用户已指定采用个人项目作为小组第一轮迭代基座。

## 源码与版本

| 项目 | 固定来源 |
| --- | --- |
| 个人项目 | https://github.com/zhaosimuyunyu/new-campus-claw |
| 源码提交 | `5fb4aa7af535e5b0be463e8c4e4ad4584098c2af` |
| 原提交说明 | `feat: redesign chat with collapsible docked navigation and add acceptance evidence` |
| 小组接收仓库 | https://github.com/Tiamstar/CampusClaw-Team |
| 小组规约起点 | `342d754343f6067968e48b3ba604600c47234ea8` |
| 第一版分支 | `codex/baseline-v0.1.0` |
| 第一版范围 | 已提交的五个源码目录、示例配置、Compose，以及本轮修复与交付文件 |

个人目录的未跟踪验收文件、运行数据库、上传资料、模型凭据和旧报告保留在原处。首次导入采用已提交源码，来源提交号用于追溯。

第三方技能保留原始许可证和版本信息。Anthropic 与 Superpowers 来源见 `backend/core/vendor_skills/sources.json`，OpenAI 技能版本见 `backend/core/vendor_skills/codex/sources.json`。基础版沿用原项目的来源声明，整体开源许可证由团队另行确定。

上述通用技能记录对应 v0.1.0-baseline 标签。后续教学更新已移除当前通用目录，新的固定来源与许可保存在 `backend/core/teaching_skills/`，详见 [教学技能选型](teaching-skills-research.md)。

## 实际架构

```text
Vue 3 + TypeScript → Nginx → Django / DRF / JWT
                                  ├─ PostgreSQL 16 / pgvector / pg_trgm
                                  ├─ 模型与 Embedding 网关
                                  ├─ MCP 工具服务
                                  └─ 内部执行代理 → 临时执行容器
```

Course 是当前成员隔离上下文，Membership 记录用户在该课程的教师或学生角色。同一用户可在不同课程担任不同角色。班级扩展应在这个模型上明确映射后接入。

基础版助手配置属于个人与课程组合。学生可以修改自己的助手配置，其他人的配置保持私有。课程要求的“教师管理课程公共提示词与技能，学生只能使用”需要单独新增公共配置模型与权限，再验收 SEC-03。

## 本轮交付

1. 邮箱验证码、JWT 登录与刷新轮换、教师邀请码、课程码和成员角色。
2. 授权资料上传下载、提取与索引状态、关键字和向量检索。
3. 作业发布、带截止规则的提交版本、教师与本人下载权限。
4. Agent 线程、SSE、取消、附件与生成文件、HTML 隔离预览。
5. 私有助手与技能配置、内置技能、ZIP 上传、MCP 工具发现与调用、隔离执行。
6. 本轮安全回归、元数据审计、数据库就绪检查、随机配置、依赖锁文件、统一检查与 CI。

完整课程底座还需教师批改复核、正式成绩与错题业务。当前任务随流式请求执行，资料索引也在请求内运行。消息队列、202 任务受理与后台恢复留给下一轮。E1、E3、E4、E5 为后续 P0 扩展，E2、E6、E7 保持 P1。

## 本轮修复

| 触发条件 | 修复后行为 | 回归依据 |
| --- | --- | --- |
| Agent 接口收到数组、null 或错误 JSON | 400，业务数据保持一致 | `test_invalid_json_is_400_without_creating_thread` |
| GET 请求重建资料索引 | 405，索引与模型调用保持未触发 | `test_reindex_get_cannot_start_external_work` |
| 对话准备后成员资格被撤销 | 工具执行时重新检查线程所有者与课程成员 | `test_revocation_between_prompt_and_tool_execution` |
| 数据库连接中断 | `/health/` 返回 503，响应隐藏内部错误 | `test_readiness_detects_database_outage` |
| API 成功、拒绝或工具调用 | 生成请求号，写入数据库及单行 JSON 元数据审计 | 审计与拒绝回归用例 |
| 缺少或使用弱 Django 密钥 | 启动配置校验明确失败 | settings 配置检查与本地初始化脚本 |
| 依赖漏洞或安装漂移 | 锁定 Python 传递依赖，前端使用 npm ci，更新已知漏洞版本 | 安全检查与锁文件 |

## 部署检查

本地 Compose 端口只绑定环回地址，默认使用 mock 与 Mailpit。各项端口和真实服务配置见 `.env.example`。

公网发布需配置实际 HTTPS 入口、ALLOWED_HOSTS、CORS_ALLOWED_ORIGINS 和 COOKIE_SECURE。执行代理与 Docker socket 留在内部网络，外部 MCP 主机由运维显式加入白名单。构建镜像对应固定提交，发布后通过健康检查切换流量。

发布前备份 PostgreSQL 与上传文件卷，先在独立环境恢复并核对账号、资料与提交。当前新增迁移仅创建审计表，旧业务字段保持兼容。回滚应用镜像时保留新增表，待数据保留策略确认后再清理。恢复目标、真实负载、域名和用户反馈需团队补充。

## 验收与审核

本轮自动化证据见根目录 `report.md` 和 `reports/`。基础版提交到独立分支供团队评审。成员按 README 在自己的机器上启动、核查高风险代码并签署记录后，才能登记为独立交叉验收通过。
