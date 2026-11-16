# 基础版流水线

配置位于 `.github/workflows/baseline.yml`，在 main、codex 分支 push 或 PR 时执行，同一分支的新运行会取消旧运行。

2026-11-16本地修复：交付冒烟已适配助手revision和MCP一次性确认，独立mock项目29次真实HTTP检查及真实MCP/隔离执行通过，见 [执行记录](ci-smoke.md)。成功/失败保留合成业务数据并逐步写状态，CI失败仍尝试上传脱敏证据；临时runner结束后数据持久性受平台生命周期限制。当前无该提交的GitHub成功运行，不改变下面历史账单阻塞结论。

流水线依次初始化独立配置与数据库、构建后端、执行功能检查、安全检查和 OpenSpec 严格校验，再构建前端、MCP、执行代理及隔离镜像，启动服务并运行真实 HTTP/MCP/隔离执行冒烟。成功后保留对应提交号、镜像元数据和前后端镜像包七天。

基础版源码已提交到 `codex/baseline-v0.1.0`，首个提交为 `87c597ac67aa80dc7f9dc01fc1f1aec6980606a2`。

push 运行 `41791073786` 与 PR 运行 `41791217616` 均在开始执行步骤前被 GitHub 阻断。检查注释明确返回 `The job was not started because your account is locked due to a billing issue.`。这两次运行没有执行测试或构建，当前远端结论为受账号账单限制阻塞。

仓库所有者处理账号账单锁定后，可重新运行工作流。当前本地功能与安全检查结果见 `gate-red-green.md`，本地镜像与真实工具验证见 `boot-reproduce.md`。

[首个 push 运行](https://github.com/Tiamstar/CampusClaw-Team/actions/runs/41791073786) · [PR 运行](https://github.com/Tiamstar/CampusClaw-Team/actions/runs/41791217616) · [基础版 PR](https://github.com/Tiamstar/CampusClaw-Team/pull/1)

[GitHub Actions 工作流记录](https://github.com/Tiamstar/CampusClaw-Team/actions/workflows/baseline.yml)

检查时 main 的 protected 为 false，当前账号具有 push 权限而无 admin 权限。仓库管理员需将检查配置为主干必需状态，团队成员完成交叉评审后再合入。

2026-11-16只读复查：最近旧运行41993300903（6c2603639e7b4447304e7b9c67a7a70b4536b1b6）仍在步骤开始前收到账号账单锁定注释；main protected=false，当前权限admin=false。未触发新运行，不能以旧运行代替当前提交CI。生产HTTPS本机预演另见 [审核](https-deployment.md)，不改变远端阻塞结论。
