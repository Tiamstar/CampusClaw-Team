# 本地独立启动复现

日期为 2026-11-04。环境为 Windows、Docker Desktop Linux 引擎 28.1.1、Node.js 24.19.0。小组项目使用新的 `campusclaw-team` Compose 项目和独立数据卷，保留个人项目环境。

执行本地随机配置初始化、构建后端与服务镜像，再执行下列命令。

```sh
docker compose up -d --wait --wait-timeout 180
docker compose ps
python scripts/check.py
python scripts/smoke.py --sandbox
```

数据库、后端与前端健康检查通过，Mailpit 健康，MCP 与执行代理正常运行。应用入口 `http://localhost:5174/` 返回 200，就绪检查返回 `{"status":"ok","database":"ok"}`。

最终 HTTP 冒烟共 20 次请求通过，覆盖健康检查、应用页面、匿名拒绝、三个临时账号登录、教师创建课程、学生加入、教师发布作业、学生操作拒绝、跨课程检索拒绝、他人对话拒绝、mock SSE 完成、平台工具发现、绑定与真实 MCP 公式工具调用，并在更新后的隔离容器执行 Python 求和，结果为 5050。临时账号和课程在脚本结束后删除。

隔离镜像已按锁文件构建，实际运行版本为 pypdf 6.21.4、Pillow 13.0.0、pandas 3.1.0，pip check 通过。最终镜像 ID 为 `sha256:5e0f0f1c29c370963b1a5623d80acb0fd9673eccfb42a363cc0145558fe18e79`。本机使用 README 中的清华镜像源参数完成构建，默认构建仍使用官方源。

另一位成员按 README 在自己机器上的复现仍待执行。本地初始化与自动测试覆盖基础版范围，完整课程主路径和公网验收继续按根报告推进。

脱敏请求结果见 [HTTP 冒烟记录](smoke-result.json)。本次使用 mock 模型和真实 MCP/隔离执行，真实外部模型与 Embedding 回归留待配置后执行。
