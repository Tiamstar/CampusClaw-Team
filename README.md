# CampusClaw 2.0

智能测验、课程答疑与学情分析扩展平台。基于课堂 CampusClaw 底座，面向高校教师和学生补齐测验、答疑、成绩与知识点学习闭环。

> 当前状态：**规约初稿，待双方评审**。本仓库尚未接入课堂底座、编写业务代码或完成部署；文档中的功能、接口和验收场景均是目标，不代表已实现或已通过测试。

## 项目范围

| 层次 | 内容 | 本次约定 |
| --- | --- | --- |
| 课程必需底座 | 登录、班级隔离、讲义入库与检索、助手与技能、作业批改、异步任务、MCP、审计和部署 | 计划复用，但必须接入并独立验收，不能因“复用”而省略 |
| P0 新增核心 | E1 在线测验与题库、E3 课程论坛与答疑、E4 成绩册与学情分析、E5 知识图谱与学习路径 | 优先交付教学闭环 |
| P1 可选拓展 | E2 课堂互动、E6 预览与笔记、E7 通知与日程 | 核心通过后再做，可按进度裁剪 |

AI 只提供建议、草稿和解释；最终成绩、权限、统计与发布由确定性逻辑和有权限的用户把关。不做家长端、多校区运营、学科交易市场、学术不端自动判定或视频直播。

## 文档导航

| 文档 | 用途 |
| --- | --- |
| [项目章程](docs/project-charter.md) | 用户、范围、成功标准、来源与待确认事项 |
| [需求追踪矩阵](docs/requirements-traceability.md) | 课程要求、E1–E7、规约、负责人及验收编号的对应关系 |
| [架构与数据契约](docs/architecture-and-contracts.md) | 模块边界、数据口径、状态机、接口与错误约定 |
| [验收计划](docs/acceptance-plan.md) | 全新环境、账号夹具、主路径与失败路径、证据要求 |
| [协作与里程碑](docs/team-workflow.md) | 两人兼任三角色、交叉验收、阶段出口与风险 |
| [贡献指南](CONTRIBUTING.md) | 规约变更、实现、评审及归档流程 |
| 选题依据 | 见项目章程的来源说明；2026-10-14 原始 DOCX 保留本地，不随仓库公开 |

## OpenSpec 变更包

采用 `proposal → specs → design → tasks → 实现 → 验收 → 归档` 的组织方式。以下变更均为草案，任务均未完成：

1. [接入与验证课程底座](openspec/changes/establish-course-foundation/proposal.md)：课程主路径、五项 AI 能力、安全和公网交付。
2. [实现 P0 教学闭环](openspec/changes/add-core-teaching-loop/proposal.md)：测验、论坛、成绩册、知识图谱。
3. [扩展 P1 课堂体验](openspec/changes/add-classroom-experience/proposal.md)：互动、预览、通知；不能替代 P0 验收。

`openspec/specs/` 暂不写入生效规约；待实现、交叉验收通过后再合并 delta 并归档。各变更的 `specs/*/spec.md` 使用 `SHALL` 与 `GIVEN / WHEN / THEN` 表达可检查的目标。

### 校验规约

需要 Node.js 20.19.0 或更高版本与 npm。校验工具固定为本次采用的 OpenSpec 1.15.0，不安装业务依赖或全局工具：

```sh
npx --yes --package=@fission-ai/openspec@1.15.0 openspec list
npx --yes --package=@fission-ai/openspec@1.15.0 openspec validate --all --strict --no-interactive
```

校验通过只说明规约格式合规，不意味着业务功能已经通过验收。目前没有可运行的前后端、测试套件、容器配置或线上演示地址。

## 成员

| 成员 | 规约、开发与自测 | 独立交叉验收 |
| --- | --- | --- |
| 李非凡 | E1、E4、E2 | E3、E5、E6、E7 |
| 陈志康 | E3、E5、E6、E7 | E1、E4、E2 |
| 共同 | 底座接入、知识点契约、部署、联调与答辩 | 共同模块由非实现主责者验收 |

## 依据

- [课程小组项目说明](https://devops.hello1023.com/项目介绍.html)
- [课程分组要求](https://devops.hello1023.com/index.html#requirements)
- [OpenSpec 官方仓库](https://github.com/Fission-AI/OpenSpec)

课程网页核对日期：2026-10-28。若后续课程要求变化，先更新追踪矩阵和规约，再更新实现；不静默改变验收口径。
