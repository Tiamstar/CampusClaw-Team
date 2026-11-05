# CampusClaw Team · v0.1.0 基础版

采用个人项目 `new-campus-claw` 的 `5fb4aa7af535e5b0be463e8c4e4ad4584098c2af` 作为第一轮迭代基座，增加安全回归、审计、依赖锁定与自动检查。基础版支持账号、课程成员、资料与作业提交、课程 Agent、技能及 MCP。E1–E7 小组扩展按现有规约后续实施。

[源码与第一版交付范围](docs/baseline-v0.1.0.md) · [第 9、10 课检查结论](report.md) · [需求与验收](docs/requirements-traceability.md) · [贡献指南](CONTRIBUTING.md)

## 技术栈

| 部分 | 当前实现 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite、Vitest，版本见 frontend/package-lock.json |
| 后端 | Python 3.13、Django 5.2、DRF、SimpleJWT、ASGI / Gunicorn / Uvicorn |
| 数据 | PostgreSQL 16、pgvector 2048 维嵌入、pg_trgm 关键字检索、Docker 数据卷 |
| AI | OpenAI 兼容或 Anthropic 接口、默认 mock、SSE、技能目录、MCP Streamable HTTP |
| 执行与部署 | Docker Compose、Nginx、Mailpit、内部执行代理、临时隔离容器 |

Python 的四个组件都使用各自 requirements.lock。当前异步对话依附 SSE 请求，资料索引仍在请求内执行。持久化消息队列列入下一轮工作。

## 教学技能与应用

当前内置目录为 16 项教学技能，覆盖备课设计、作业测评、个别辅导、错题复习、编程实验和资料研读。13 项按固定版本改编自公开 MIT 教学技能，保留原文和许可。调研与清单见 [教学技能选型](docs/teaching-skills-research.md)。

进入课程的“能力中心”，在“AI 应用”选择教学方向，会自动绑定对应技能，保留个人上传技能和知识库偏好。技能广场支持按教学方向和实际来源筛选。详情可查看中文步骤、参考文件与固定版本来源。

## 从空目录启动

准备 Git、Python 3.13、Docker Desktop Linux 引擎。首次构建需要网络下载镜像和依赖。自动检查额外需要 Node.js 22 或 24。

```sh
git clone https://github.com/Tiamstar/CampusClaw-Team.git
cd CampusClaw-Team
git switch codex/baseline-v0.1.0
python scripts/setup_local.py
docker compose --profile build build sandbox-image
docker compose up --build -d --wait --wait-timeout 180
```

`setup_local.py` 一次性生成四个随机凭据到 `.env`，已有配置会保留。Compose 使用独立的 `campusclaw-team` 项目名及数据卷。

隔离镜像下载慢时可指定镜像源重试，其余启动步骤相同。

```sh
docker compose --profile build build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple --build-arg APT_MIRROR=mirrors.tuna.tsinghua.edu.cn sandbox-image
```

- 应用入口为 http://localhost:5174 。
- 测试邮箱为 http://localhost:8026 。
- 就绪检查为 http://localhost:5174/health/ ，数据库连接失败返回 503。
- 存活检查为 http://localhost:5174/health/live/ 。
- 管理后台为 http://localhost:5174/admin/ 。

创建管理员后，在后台 Teacher invites 创建教师邀请码。应用注册的邮箱验证码可在 Mailpit 查看，用户兑换教师邀请码后创建课程，学生用课程码加入。

```sh
docker compose exec backend python manage.py createsuperuser
docker compose ps
```

默认 mock 可用于本地对话与流程验证。真实模型、RAG 需在 `.env` 填写 `MODEL_PROVIDER`、模型地址、名称和密钥，以及 `EMBEDDING_BASE_URL`、模型、密钥和 2048 维配置，再重建后端。地址按照兼容服务要求以 `/v1` 结尾。真实 SMTP 按 `.env.example` 配置。

本轮本机已复用个人项目的模型、Embedding 与 SMTP 配置，实际验证见 [教学更新记录](reports/teaching-update.md)。新克隆环境仍需自行配置这些服务，仓库中的示例保持空值。

## 检查与开发

启动数据库并构建后端后，运行统一检查。它检查迁移漂移、后端回归、前端测试和生产构建，任一失败都会返回非零退出码。

```sh
python scripts/check.py
python scripts/smoke.py --sandbox
npx --yes --package=@fission-ai/openspec@1.15.0 openspec validate --all --strict --no-interactive
```

安全检查需要 Python 环境安装 `pip-audit==2.10.1`，并将 Gitleaks 8.30.1 加入 PATH。检查覆盖 Git 历史、待提交文件、四组 Python 锁文件及前端依赖。前端高危及以上阻断，剩余中危的处置见报告。

```sh
python -m pip install pip-audit==2.10.1
python scripts/check.py --security
```

Linux/macOS 也可运行 `make check` 和 `make check-security`。GitHub Actions 在分支 push 和 PR 时执行检查、构建镜像并保留提交对应的制品。

前端热更新可在 `frontend` 下执行 `npm ci`、`npm run dev`，开发代理指向后端本机 8001 端口。后端代码变更后执行 `docker compose up --build -d backend`。

## 审计与运维

API 响应包含服务端生成的 `X-Request-ID`。元数据审计记录成功、拒绝与工具调用，运维人员可按用户、技能和时间查询。

```sh
docker compose exec -T backend python manage.py audit_events --minutes 60 --limit 100
docker compose logs --tail 100 backend
docker compose down
```

审计中 tokens 为 null 表示尚未采集模型用量。HTTP 耗时表示处理到响应头的时间，工具记录有独立执行耗时。完整 SSE 耗时及技能监控面板属于后续交付。

`down` 保留数据库和文件卷。生产发布前按 [部署检查](docs/baseline-v0.1.0.md) 完成 HTTPS、域名、安全 Cookie、备份恢复、容量与公网验收。

## 规约与下一轮

- [项目章程](docs/project-charter.md) 明确底座与 P0/P1 边界。
- [架构与数据契约](docs/architecture-and-contracts.md) 描述后续扩展的逻辑契约。
- [验收计划](docs/acceptance-plan.md) 保留完整教学闭环的目标。
- [工程规则](AGENTS.md) 和 [本次变更](openspec/changes/2026-11-04-import-personal-baseline/proposal.md) 约束第一版实现与审核。

成员为李非凡、陈志康，按功能线交叉验收。当前基础版的自动化验证结果与成员交叉验收分别记录。

## 作业提交与教师批改

已支持文字、多附件、人工评分、成绩公开/撤回和文件大窗预览。使用说明、格式限制及验证见 [作业功能交付](docs/homework-review.md)。AI 自动批改和错题闭环尚未实现。
