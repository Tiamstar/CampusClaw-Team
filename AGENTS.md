# CampusClaw Team 工程规则

2026-11-16用户最新范围决定见 docs/delivery-scope.md：公网改为本轮附加项，不阻塞本地交付；容量/RPO/RTO/保留期未确定，不自行编造或宣称达标。历史课程完整交付要求和未执行证据保留，真人独立验收不可代签。

## 当前交付

当前维护个人项目导入的 v0.1.0 基础版。来源、范围和证据见 README.md、docs/baseline-v0.1.0.md 和 report.md。E1–E7 仍按 OpenSpec 草案单独实施，接入基础版不代表扩展已完成。

E1 测验已实施与自测，见 docs/quiz-delivery.md；E4 成绩册第一阶段见 docs/gradebook-delivery.md，学情与只读 MCP 已实现和自测，见 docs/learning-mcp-delivery.md；学情诊断与同版 HTML/PDF 已本地实现与自测，见 docs/diagnostic-delivery.md。E3 论坛已实施到本地可用，证据和限制见 docs/forum-delivery.md；E5 图谱抽取、校对、无环审批和指标着色见 docs/graph-delivery.md；复习路径与站内间隔提醒已实现、自测，见 docs/review-path-delivery.md。用户指定的两个本地验收账号产生的课程、帖子、草稿、提交和批改记录应保留供用户查看，不清理这些验收记录。密码不写入仓库或公开证据。

E1 题库导入当前支持模板化 XLSX / DOCX，限制和不支持内容见 docs/quiz-delivery.md 与 OpenSpec QZ-008。它不支持 PDF、扫描/OCR、任意版式抽题或语义验证；必须保留逐行预览、全批校验、幂等重试和全有或全无写入。实现者自测不得记为两位组员的工作已通过或独立验收完成。

资料持久化索引、取消/重试、后台恢复与真实账号证据见 docs/material-index-delivery.md；AI 作业批改草稿、逐项教师复核、个人错题与讲解见 docs/coursework-ai-delivery.md，实际交付状态与限制以该记录为准。三项技能统一开关、私有解题引导、真实网关用量和教师运行监控见 docs/teaching-skills-monitor-delivery.md；未上报用量不得当作零，演示调用不得计为真实服务证据。课程公共助手权限、版本检查和私人内容保留见 docs/course-assistant-delivery.md。当前内置目录已转为教学技能，来源与适配规则见 docs/teaching-skills-research.md。修改技能须保留来源和许可，并保持用户上传技能的私有性及旧绑定兼容。常规检查使用 mock，真实模型验证通过显式 --real 命令执行。

SEC-08真实四步实验、模型虚假完成修正与教师课程审计见 reports/sec08-experiment.md 和 reports/review-sec08.md；初测不良表现与复测均保留，不把模型观察或强制重放混作同一证据。

本地k6三目标20VU×60秒对照、容量阶梯、ready片段GIN索引与备份迁移证据见 reports/bench.md。纯建索引未收益的运行同样保留；不能把单账号虚拟客户端、受理吞吐或短时探测当成多人真实批改容量。

MCP一次性确认、所有者私有卡片、版本/定义绑定、5分钟过期与并发消费见 docs/mcp-confirmation-delivery.md，真实账号课程11与审核依据见 reports/review-mcp-confirmation.md；未知副作用的超时或崩溃不得自动重放。

完整HTTP响应耗时与三技能模型/任务/处理/排队曲线见 docs/latency-monitor-delivery.md，真实课程7及七类七维自审见 reports/review-latency-monitor.md；旧审计与未知领取时间不得混用或补零。

固定 SQL/XSS/CSRF 反例、真实 HTTP 与浏览器渲染证据见 apitest/README.md、reports/security-negative.md 和 reports/security-negative-evidence.json；存储原文不替代实际页面渲染结论。

组员交叉验收按 docs/team-acceptance-packet.md 执行；未填写的独立验收、真实反馈、公网、容量和主干保护项目不得标记为已完成。

2026-11-17 试卷识别与题库重构见 docs/exam-bank-delivery.md、reports/review-exam-bank.md：新增所有者私有 TXT/图片/DOCX/PDF 识别草稿、共享材料题组、来源映射与固定组卷。新题库不要求分值，答案可暂空，组卷逐题设分，无答案键须人工批改。上文 PDF/OCR 不支持的描述仅适用于旧模板导入；模型识别存在漏题和裁图缺陷，不得宣称任意试卷无误自动入库。

## 每次修改

整卷编辑、外键题目索引、跨题库版本同步、可恢复归档和真实AQA样本结果见 docs/editable-paper-design.md、reports/review-editable-paper.md。模拟照片不是实拍证据；不能把模型结构成功当成裁图或语义校对通过。

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

保留课程的跨模块只读回查见 reports/retained-chain.md；同一窗口/评分版本的17项一致性通过不等于完整双学生并发X01/X02或成员独立签字。

前端开发依赖修复与定向覆盖维护依据见 reports/dependency-refresh.md；升级工具链须重新核对Node22容器、格式化依赖兼容性、类型检查、回归及全量审计。

完整数据库/媒体只读快照与隔离恢复工具见 docs/recovery-rehearsal.md、reports/recovery-rehearsal.md；备份仅放仓库外的新私有目录，不覆盖源库或源卷。本机恢复观察不能替代团队冻结RPO/RTO和独立验收。

双学生并发HTTP联调工具verify_x01与课程13结果见 reports/x01.md；第二学生为不可密码登录的合成账号，人工预索引/候选夹具、真实worker计划和HTTP审批分别标注。数据保留，不把该工程自测冒充双真人演示或成员独立验收。

论坛X02同轮HTTP、真实正常草稿、教师确认与待办关闭见 reports/x02.md；注入请求生成failed且无模型原文，只能证明失败控制，空正文无攻击标记不能当作模型抵抗注入证据。

新草稿固定失败分类、隐私回归及旧失败兼容见 reports/forum-diagnostics.md；禁止在提示/审计写异常原文、失败模型输出或服务凭据，分类不能反推旧错误或证明语义抗注入。

独立空库合成夹具命令seed_acceptance见 docs/acceptance-fixtures.md；不得在现有真实教学库导入、覆盖或重置。重复导入只读原回执，保留验收人的操作；人工预索引/候选不当作模型或worker验证。密码只经环境安全输入。

生产HTTPS覆盖与内部CA预演见 docs/production-deployment.md、reports/https-deployment.md；可信代理头只在backend不发布的拓扑启用。预演必须新项目/新卷、合成数据，无宿主端口，不迁移或公开既有教学库；内部CA通过不能写成公网受信证书交付。夹具须在bootstrap_tools首次创建服务账号之前导入。

恢复来源选择及生产覆盖实测见 reports/recovery-source-selection.md；自定义Compose配置必须显式指定项目，并先核对db/backend身份、网络和数据库配置，禁止默默备份另一个本地库。备份/恢复业务数据不等于恢复TLS密钥或公网站点。

当前交付冒烟见 reports/ci-smoke.md；必须mock、显式保留合成数据并写新证据文件，读取助手revision后绑定，MCP按待确认/显式执行/拒绝重放验证。不得恢复finally删库或把密码放进命令参数；本地成功不当作账单受阻的远端CI成功。

2026-11-16 持续告警补充：连续异常/正常观察、未知保持告警、采样间断和策略变化重新观察已实现；课程15真实worker计时、保留合成样本、迁移恢复和页面证据见 [执行记录](docs/sustained-alerts.md)。工程默认120秒不等于团队冻结SLO，不改变公网、独立验收与项目未完成边界。

2026-11-17 UX基础迭代见 docs/ux-improvement-targets.md、reports/review-ux-foundation.md：分层导航、App通知队列、实时权重校验和集中组卷设分已自测；完整七方向、稳定路由、跨课程批改和独立验收仍未完成。

2026-11-18选题与组卷会话恢复、论坛解决回复/重开与公开回复搜索、两秒保存反馈见reports/review-ux-flow.md；迁移已备份隔离验证，七方向继续进行，依赖审计本轮因PyPI超时尚未通过。

2026-11-18论坛自动相似讨论提示、保留正文返回编辑、角色筛选与匹配层级排序见reports/review-ux-forum-discovery.md；确认仅为前端UX引导，跨刷新问题/教师草稿恢复仍未完成。

2026-11-18论坛未发布问题/教师回复修订的账号课程隔离会话恢复见reports/review-ux-forum-drafts.md；非跨设备草稿箱，发布确认不恢复，退出登录清除。

2026-11-18复习最新轮次进度与用户可调预估见reports/review-ux-review-progress.md；80%指提醒完成度而非评分掌握度，真实学生页面已查看，不代替独立验收。

2026-11-18七个工作区统一加载骨架与移动/减少动画样式见reports/review-ux-skeleton.md；其他工作区与逐页浏览器复验仍待完成。

2026-11-18大型工作区按需加载与失败页见reports/review-ux-lazy-workspaces.md；主入口约535kB仍有体积告警，未把分块构建当首屏性能实测。

2026-11-18 证据驱动学情概览见reports/review-ux-learning-summary.md；跨标签题次去重，未知非零，不代表整门课程成绩或完整个人学习中心。

2026-11-18 课程模块/作业/答卷稳定路由见reports/review-ux-routing.md；前进后退沿用未保存拦截，旧答卷哈希兼容，细粒度论坛/原卷/对话路由仍待完成。

2026-11-18 错题工作区概览与时间筛选见reports/review-ux-wrong-answers.md；只消费公开逐项复核证据，不从整体分数推断错题。

2026-11-18 错题自评持久化与0031迁移见reports/review-wrong-answer-state.md；按评分版本绑定，不将自评混为正式掌握度，备份与隔离迁移先于本地升级。

2026-11-18 跨课程作业批改中心第一阶段见reports/review-grading-center.md；只读本人任课队列，非测验聚合或批量AI交付。

2026-11-18 同冻结试卷按题对比与单题正式评分见reports/review-question-comparison.md；全量264后端/132前端通过，浏览器确认框控制超时未验收，不将入口查看等同保存或移动布局通过。

2026-11-18 本页最多20份串行AI测验评阅与逐题采用见reports/review-batch-quiz-review.md；不自动改正式评分，非持久后台批量任务，真实模型批量及浏览器采用待验证。

2026-11-18 真实图文测验评阅发现选择题索引误读，v2显式选项标签修正及保留错误/复测建议见reports/review-batch-quiz-review.md；真实结构成功不等于语义通过，旧编码不自动恢复采用。

2026-11-18 原卷裁图预览/键盘坐标微调见reports/review-crop-preview.md；不自动扩边、不替换冻结题图，真实旧图重新裁剪与浏览器触屏验收仍待做。

2026-11-18 角色化课程首页与默认课程入口见reports/review-course-overview.md；只读汇总本人作业/答卷和教师批改待办，队列范围共用，不在GET交卷，非持久通知或完整个人仪表盘。全量273后端/148前端/20脚本通过，师生课程6及手机布局已查看；Gitleaks与四份pip-audit通过，npm的picomatch高危仍未解决。

2026-11-18 UX-025持久成绩通知与0032迁移见reports/review-grade-notifications.md；按当前成员/评分版本动态展示，显式已读，非邮件或实时推送。课程6保留合成作业14/测验5/答卷8；初验脚本数值字符串断言失败，随后只读复核通过，不得将初验写成全程成功。

2026-11-18 UX-026所有者题库组合筛选见reports/review-bank-filters.md；按最近成功条件分页，重置回首页，不改材料题组/选题篮。283后端/158前端与生产构建通过，教师课程6和手机已复验；难度/推荐分值仍待实现，七方向未完成。

2026-11-18 UX-027作业入口加载/失败重试见reports/review-assignment-loading.md；真实教师已观察骨架后列表及详情，283后端/159前端通过。首次登录仍用全局恢复提示，未改真实评分，完整七方向继续进行。

2026-11-18 UX-028论坛帖子独立地址见reports/review-forum-links.md；283后端/163前端通过，浏览器完整深链接尚待验收。用户要求先Git提交/推送，保持七方向未完成和真实数据保留。
