# 本地独立启动复现

日期为 2026-11-04。环境为 Windows、Docker Desktop Linux 引擎 28.1.1、Node.js 24.19.0。小组项目使用新的 `campusclaw-team` Compose 项目和独立数据卷，保留个人项目环境。

执行本地随机配置初始化、构建后端与服务镜像，再执行下列命令。

```sh
docker compose up -d --wait --wait-timeout 180
docker compose ps
python scripts/check.py
python scripts/smoke.py
```

数据库、后端与前端健康检查通过，Mailpit 健康，MCP 与执行代理正常运行。应用入口 `http://localhost:5174/` 返回 200，就绪检查返回 `{"status":"ok","database":"ok"}`。

首轮 HTTP 冒烟共 18 次请求通过，覆盖健康检查、应用页面、匿名拒绝、三个临时账号登录、教师创建课程、学生加入、教师发布作业、学生操作拒绝、跨课程检索拒绝、他人对话拒绝、mock SSE 完成、平台工具发现、绑定与真实 MCP 公式工具调用。临时账号和课程在脚本结束后删除。

脚本随后增加了显式 mock 模式校验，最终带隔离执行的结果随本轮验证更新。隔离镜像采用新的锁文件重建，本机下载依赖较慢，构建与运行结果以最终验证记录为准。

另一位成员按 README 在自己机器上的复现仍待执行。本地初始化与自动测试覆盖基础版范围，完整课程主路径和公网验收继续按根报告推进。
