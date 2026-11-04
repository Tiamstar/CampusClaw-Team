# 基础版流水线

配置位于 `.github/workflows/baseline.yml`，在 main、codex 分支 push 或 PR 时执行，同一分支的新运行会取消旧运行。

流水线依次初始化独立配置与数据库、构建后端、执行功能检查、安全检查和 OpenSpec 严格校验，再构建前端、MCP、执行代理及隔离镜像，启动服务并运行真实 HTTP/MCP/隔离执行冒烟。成功后保留对应提交号、镜像元数据和前后端镜像包七天。

本轮源码将提交到 `codex/baseline-v0.1.0`，实际运行记录可从仓库的工作流页面核对。具体运行编号与结论在推送后登记。

[GitHub Actions 工作流记录](https://github.com/Tiamstar/CampusClaw-Team/actions/workflows/baseline.yml)

检查时 main 的 protected 为 false，当前账号具有 push 权限而无 admin 权限。仓库管理员需将检查配置为主干必需状态，团队成员完成交叉评审后再合入。
