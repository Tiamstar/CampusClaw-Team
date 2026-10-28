# 需求追踪矩阵

版本：0.1 初稿。所有条目当前均为**待评审 / 未实现 / 未验收**；负责人表示计划分工，不是已完成贡献。验收编号的具体操作见 [验收计划](acceptance-plan.md)。

## 来源到规约

| 来源与边界 | 能力规约 | Requirement ID | 验收编号 | 实现主责 / 验收 |
| --- | --- | --- | --- | --- |
| 课程：登录、班级隔离、讲义、助手、作业与错题三主路径；复用但必验 | [course-core](../openspec/changes/establish-course-foundation/specs/course-core/spec.md) | FND-001–004 | AC-F01–F04 | 共同指定主责 / 另一位 |
| 课程：大语言模型、知识库与 RAG、智能体、技能、MCP 五项能力 | [ai-platform](../openspec/changes/establish-course-foundation/specs/ai-platform/spec.md) | AI-001–005 | AC-A01–A05 | 共同指定主责 / 另一位 |
| 课程：权限、服务端密钥、安全和审计 | [delivery-security](../openspec/changes/establish-course-foundation/specs/delivery-security/spec.md) | SEC-001–003 | AC-S01–S03 | 共同指定主责 / 另一位 |
| 课程：公网应用、测试、性能与交付证据 | [delivery-security](../openspec/changes/establish-course-foundation/specs/delivery-security/spec.md) | DLV-001–002 | AC-D01–D02 | 共同指定主责 / 另一位 |
| 初步设计 E1：测验与题库，P0 | [quiz](../openspec/changes/add-core-teaching-loop/specs/quiz/spec.md) | QZ-001–007 | AC-Q01–Q07 | 李非凡 / 陈志康 |
| 初步设计 E3：论坛与答疑，P0 | [forum](../openspec/changes/add-core-teaching-loop/specs/forum/spec.md) | FRM-001–004 | AC-FR01–FR04 | 陈志康 / 李非凡 |
| 初步设计 E4：成绩册与学情，P0 | [gradebook](../openspec/changes/add-core-teaching-loop/specs/gradebook/spec.md) | GRD-001–005 | AC-G01–G05 | 李非凡 / 陈志康 |
| 初步设计 E5：知识图谱与路径，P0 | [knowledge](../openspec/changes/add-core-teaching-loop/specs/knowledge/spec.md) | KNO-001–004 | AC-K01–K04 | 陈志康 / 李非凡 |
| 初步设计 E2：课堂互动，P1 | [classroom-interaction](../openspec/changes/add-classroom-experience/specs/classroom-interaction/spec.md) | INT-001–003 | AC-I01–I03 | 李非凡 / 陈志康 |
| 初步设计 E6：预览与笔记，P1 | [preview-notes](../openspec/changes/add-classroom-experience/specs/preview-notes/spec.md) | PRE-001–003 | AC-P01–P03 | 陈志康 / 李非凡 |
| 初步设计 E7：通知与日程，P1 | [notifications-calendar](../openspec/changes/add-classroom-experience/specs/notifications-calendar/spec.md) | NTF-001–003 | AC-N01–N03 | 陈志康 / 李非凡 |

## 五项 AI 能力的真实业务落点

| 课程能力 | 底座与新增场景 | 必须检查的结果 |
| --- | --- | --- |
| 大语言模型 | 引导、评分建议、答疑草稿、诊断和抽取 | 服务端调用及失败反馈，不把模型意见直接当成绩 |
| 智能体 | 多步诊断和复习路径 | 读取授权数据、可取消、步骤可追踪、失败保留草稿 |
| 知识库 / RAG | 讲义检索、课程问答、知识点抽取 | 真引用、课程过滤、未命中说明、提示注入负例 |
| 技能 | 原有解题引导/作业批改/错题讲解；新增答疑草稿/学情诊断/知识点抽取 | 六项分别有可调用结果、版本和启停负例 |
| MCP | 底座工具；新增成绩/测验统计/掌握度只读工具 | 不是普通聊天接口改名，须有协议工具调用、参数约束、权限和审计证据；写入需确认 |

## 依赖顺序

1. 底座来源、真实权限与共享数据契约先确认。
2. E5 的稳定知识点 ID 与 E1 的评分版本先联调，再做 E4 汇总和诊断；知识抽取 AI 可与人工知识点维护并行。
3. E3 复用资料引用契约，与 E1 可分线实施。
4. P0 的提醒用站内待办，不依赖 P1；E6 / E7 不能成为 P0 隐藏前置。
5. 公网部署、全链路隔离与真实 AI / MCP 验证贯穿，不留到答辩时补证据。

## 范围与状态维护

- Requirement ID 一经进入实现或验收记录不再复用；拆分和废弃保留映射。
- 每次提交实现时在 PR 引用 Requirement ID 与验收编号，更新任务但不提前勾选独立验收。
- P1 未启动为“未纳入当前交付”，不是失败，也不是已完成；启动或裁剪需双方记录。
- 共同模块必须在实现开始前指定单项主责与独立验收人，不能用“共同”规避责任。
