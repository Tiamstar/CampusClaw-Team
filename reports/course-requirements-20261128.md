# 课程要求与选题核对

核对日期为 2026-11-28。选题来源为仓库根目录的 [CampusClaw 选题说明](../CampusClaw选题说明(1).docx)。

## 课程原文要求摘要

| 课次 | 要求和可检查产物 |
| --- | --- |
| 第 7 课 | 小组共用仓库与角色分工，写清产品范围和验收。落盘 Harness 规则、规约和部署运维约定，骨架打标签，保存启动和验证记录。队友在另一台机器从零启动。 |
| 第 8 课 | 提交快速返回 202 与任务 ID，可查询状态。停消费者后恢复仍能执行，重复提交或投递只有一份结果。提交与任务写入具有事务保证。完成 SEC-01–07 自查，保留红项、准备 SEC-08，沉淀七类七维 AI 代码审核。 |
| 第 9 课 | 用同一操作复测修复前后。覆盖认证与归属、角色、底层工具授权、SQL/XSS/CSRF 防护、密钥、依赖、审计和 SEC-08 四步。固定自动门禁，保存红绿输出和提交号。另一成员独立复现至少两条。 |
| 第 10 课 | 收口自动测试、容器、流水线及降级和恢复验证。监控按技能调用量和错误率、接口 P95 与队列深度。以相同 k6 脚本和 20 VU × 60 秒参数比较提交、查询、检索优化前后 P95、吞吐及错误率。收集真实用户反馈。队友独立复跑登录、202、轮询完成、跨班 404 四步。 |
| 第 11 课 | 根目录单一、约一至两页的 report.md，与课堂派内容一致。开头写仓库、视频下载地址、可追溯分工及 Harness。六节评分分别为产品一句话 10、AI 产出与七类核查 20、至少三份可复核审核且至少两份出自 AI 自审或脚本 25、并发／事务／权限三查 25、红绿门禁与现场可见验证命令的演示视频 20、最大返工复盘不计分。 |

来源见 [课程目录](https://devops.hello1023.com/#schedule)、[小组项目说明](https://devops.hello1023.com/项目介绍.html)、[第 7 课任务](https://devops.hello1023.com/课程任务清单-第7课.html)、[第 8 课任务](https://devops.hello1023.com/课程任务清单-第8课.html)、[AI 代码审核](https://devops.hello1023.com/小组项目/小组项目下一阶段重点-AI代码审核.html)、[第 9 课任务](https://devops.hello1023.com/课程任务清单-第9课.html)、[第 10 课任务](https://devops.hello1023.com/课程任务清单-第10课.html)、[第 11 课评分](https://devops.hello1023.com/课件/第11课-课件-展示与复盘/index.html)。

## 选题功能与缺口

| 选题项 | 当前实现与证据 | 待补或待核验 |
| --- | --- | --- |
| E1 测验与题库，P0 | 五题型、知识点、随机与固定组卷、冻结试卷、版本自动保存、服务端截止、确定性评分、手写图、AI 建议和教师复核、正确率和区分度。见 [测验交付](../docs/quiz-delivery.md) 和 [批量 AI 评阅](review-batch-quiz-review.md)。 | 本轮补强新题库按知识点随机组卷并按题型设分，以及论坛扫描故障后的自动交卷。两位真人同轮走查、真实图文建议逐题语义复核仍待验。 |
| E2 课堂互动，P1 | [INT-001–003 草案](../openspec/changes/add-classroom-experience/specs/classroom-interaction/spec.md)。 | 签到与补签、投票抢答、匿名弹幕、出勤统计。 |
| E3 课程论坛，P0 | 帖子和回复、匿名、@教师、置顶精华、相似帖、带引用的教师 AI 草稿、超时提醒。见 [论坛交付](../docs/forum-delivery.md)。 | 独立验证未命中拒答、真实引用、确认发布与提醒关闭。 |
| E4 成绩册与学情，P0 | 权重、汇总、Excel、本人和班级学情、可取消的诊断草稿及同版 HTML/PDF。见 [成绩册](../docs/gradebook-delivery.md)、[学情 MCP](../docs/learning-mcp-delivery.md) 和 [诊断](../docs/diagnostic-delivery.md)。 | 签到／讨论自动归分依赖对应业务规则；诊断结论的数值和措辞仍需队友逐条核查。 |
| E5 图谱与学习路径，P0 | AI 抽取、教师校对与审批、知识点资源关联、掌握度着色、可取消的先修路径和间隔站内待办。见 [图谱](../docs/graph-delivery.md) 和 [复习路径](../docs/review-path-delivery.md)。 | 用同一评分窗口由队友回查题目、错题、节点着色及复习顺序。 |
| E6 预览与笔记，P1 | 有基础文件预览与来源展示。 | 完整 Office 转档与章节目录、跨会话阅读进度、页内私有笔记标注和引用页定位。见 [PRE-001–003](../openspec/changes/add-classroom-experience/specs/preview-notes/spec.md)。 |
| E7 通知与日程，P1 | 已有成绩通知、论坛教师待办和复习站内待办。 | 课程公告、统一事件和邮件提醒、课程日历与可撤销 iCal 订阅。见 [NTF-001–003](../openspec/changes/add-classroom-experience/specs/notifications-calendar/spec.md)。 |

五项 AI 能力在四个 P0 扩展中均有入口。真实模型的输出质量与结构或引用校验应分别验收。答疑、诊断和图谱技能开关见 [教学技能](../docs/teaching-skills-monitor-delivery.md)，三个只读 MCP 见 [学情 MCP](../docs/learning-mcp-delivery.md)，写入工具的显式确认与重放防护见 [MCP 确认](../docs/mcp-confirmation-delivery.md)。日历写入随 E7。

## 评分点的工程补强

- 第 8、10、11 课优先补可复跑的高风险判据。现有并发、事务、权限测试分别使用真实 PostgreSQL、事务失败注入和跨课程 API 请求。三份记录各自保留判据、命令和结果供队友独立复查。
- 已有 [门禁红绿](gate-red-green.md)、[流水线](pipeline.md)、[压测](bench.md)、[恢复](recovery-rehearsal.md) 和 [安全基线](security-baseline.md) 供答辩回查。实际演示录屏、成员独立验收及真实反馈仍需实际完成。容量、RPO、RTO 与保留期由团队确定；公网按 [本轮本地范围](../docs/delivery-scope.md) 作为附加项，课程完整交付的公网证据仍待补。
- 当前优先修复四个 P0 模块的失败路径。P1 三个完整模块继续列入待交付范围，供小组决定投入顺序。
- 第 10 课练习以 MySQL / Qdrant 为例，项目沿用 PostgreSQL / pgvector。答辩应展示等价职责、依赖就绪和恢复证据。任务清单还明确至少三名真实用户、手机上的四步链路、实际告警送达、提交号对应镜像、主干保护。已有响应式页面、告警状态和 CI 配置，只能分别作为这些判据的一部分。
- 第 10 课要求的四项行为为解题引导不给最终答案、教师改分优先、错题讲解不贴标准答案、知识库跨班为空。应在演示记录里分别给出规约场景、输入及可观察结果。第 11 课还要求覆盖率阈值和可检查的性能门槛，当前统一检查未设置覆盖率阈值，团队性能目标也未冻结。

队友复跑入口见 [并发](risk-concurrency.md)、[事务](risk-transaction.md)、[权限](risk-authz.md) 和 [定时任务红绿](review-scheduled-task-isolation.md)。

可用于第 11 课审核记录的实例包括 [定时任务故障隔离](review-scheduled-task-isolation.md)、[MCP 确认审核](review-mcp-confirmation.md) 和 [性能与检索索引](review-performance.md)。最终材料需按真实提交和队友复核结果填写。

新增优先功能的复查见 [新题库随机组卷](review-random-bank-quiz.md)。

## 本机部署验证

Compose 使用本机独立的 `campusclaw-team` 项目与数据卷，原有其他项目数据卷保留。默认 mock 模型与 Mailpit 登记邮件生效。应用入口为 [本机 CampusClaw](http://localhost:5174)，就绪返回数据库正常，存活返回 alive。

常规冒烟初次请求因宿主代理超时，合成账号记录保留。设置回环代理例外后，24 个 HTTP 请求通过。隔离镜像构建后，带 `--sandbox` 的 29 个 HTTP 请求全部通过，覆盖真实 MCP 与隔离容器执行。两次成功冒烟的合成课程 #1、#2 保留，随机组卷实测课程 #3 保留。

本机实际注册链路已走通。API 请求发送注册验证码返回 200，Mailpit 收到邮件，使用该验证码注册返回 201，随后登录及读取本人资料均为 200。合成账号保留，记录省略验证码、口令和令牌。

最终统一门禁退出 0，宿主脚本 20 项、后端 288 项、前端 164 项通过，迁移无漂移，前端类型检查和生产构建通过。安全门禁退出 0，Gitleaks 未发现泄漏、四组 Python 锁文件未检出已知漏洞，npm audit 报告 0 漏洞。OpenSpec 严格校验 9 项通过。生产构建仍提示大于 500 kB 的构建块。
