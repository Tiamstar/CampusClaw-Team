# CampusClaw Team 工程规则

## 当前交付

当前维护个人项目导入的 v0.1.0 基础版。来源、范围和证据见 README.md、docs/baseline-v0.1.0.md 和 report.md。E1–E7 仍按 OpenSpec 草案单独实施，接入基础版不代表扩展已完成。

E1 测验已实施与自测，见 docs/quiz-delivery.md；E4 成绩册第一阶段见 docs/gradebook-delivery.md，学情与只读 MCP 已实现和自测，见 docs/learning-mcp-delivery.md；学情诊断与同版 HTML/PDF 已本地实现与自测，见 docs/diagnostic-delivery.md。E3 论坛已实施到本地可用，证据和限制见 docs/forum-delivery.md；E5 图谱抽取、校对、无环审批和指标着色见 docs/graph-delivery.md；复习路径与站内间隔提醒已实现、自测，见 docs/review-path-delivery.md。用户指定的两个本地验收账号产生的课程、帖子、草稿、提交和批改记录应保留供用户查看，不清理这些验收记录。密码不写入仓库或公开证据。

资料持久化索引、取消/重试、后台恢复与真实账号证据见 docs/material-index-delivery.md；AI 作业批改草稿、逐项教师复核、个人错题与讲解见 docs/coursework-ai-delivery.md，实际交付状态与限制以该记录为准。三项技能统一开关、私有解题引导、真实网关用量和教师运行监控见 docs/teaching-skills-monitor-delivery.md；未上报用量不得当作零，演示调用不得计为真实服务证据。课程公共助手权限、版本检查和私人内容保留见 docs/course-assistant-delivery.md。当前内置目录已转为教学技能，来源与适配规则见 docs/teaching-skills-research.md。修改技能须保留来源和许可，并保持用户上传技能的私有性及旧绑定兼容。常规检查使用 mock，真实模型验证通过显式 --real 命令执行。

SEC-08真实四步实验、模型虚假完成修正与教师课程审计见 reports/sec08-experiment.md 和 reports/review-sec08.md；初测不良表现与复测均保留，不把模型观察或强制重放混作同一证据。

本地k6三目标20VU×60秒对照、容量阶梯、ready片段GIN索引与备份迁移证据见 reports/bench.md。纯建索引未收益的运行同样保留；不能把单账号虚拟客户端、受理吞吐或短时探测当成多人真实批改容量。

MCP一次性确认、所有者私有卡片、版本/定义绑定、5分钟过期与并发消费见 docs/mcp-confirmation-delivery.md，真实账号课程11与审核依据见 reports/review-mcp-confirmation.md；未知副作用的超时或崩溃不得自动重放。

## 每次修改

- 先读关联规约，记录 Requirement 与受影响的正常、失败、边界路径。行为变化同步文档。
- 保留现有 Vue、Django 和服务层，权限依赖真实 Membership 与对象所有者。工具执行时再次检查授权。
- 校验在写入前完成。只读 GET 不产生业务写入或外部调用。ORM 或参数化 SQL 访问数据，事务中避免模型和网络调用。
- 用户可见页面覆盖加载、正常、空状态和错误状态。文本经 Vue 转义或现有 Markdown 净化器输出，HTML 预览沿用隔离 iframe。
- 密钥只从环境加载。日志仅保留身份 ID、资源 ID、动作、结果、耗时和请求号。生产日志与教学数据留在受控存储。
- 对安全或数据一致性修复增加能复现旧问题的回归用例。执行 `python scripts/check.py`，涉及依赖或安全时执行 `python scripts/check.py --security`。
- Docker 构建使用锁文件。配置缺失应明确失败，数据库不可用时就绪检查返回 503。迁移先备份，在独立环境验证恢复与兼容性。

## AI 代码审核

按接口入口、业务逻辑、数据库操作、公共函数、错误处理、安全隐私、性能七类检查改动。审核记录写明保证什么、依据什么实现、何时失效及实际验证结果。特别核对权限、并发和事务。

评审记录按需求覆盖、一致性、失败路径、查询性能、重复逻辑、漏洞风险、高风险场景七个维度给出依据，再归类为可用、待修改或风险无效。另一名成员复核后再合入主干。记录实际执行者和证据，自动检查结果与人工交叉评审分别登记。
