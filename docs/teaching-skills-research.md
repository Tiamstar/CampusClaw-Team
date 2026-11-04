# 教学技能调研与选型

调研日期为 2026-11-04。本轮检查了六个公开仓库的目录、许可及代表性技能，目录合计约 200 个 SKILL.md。最终保留 16 项面向本平台的教学技能，其中 13 项按固定提交改编并保留原文与 MIT 许可，3 项为平台教学场景编写。

## 调研来源

| 来源 | 侧重与规模 | 本轮处理 |
| --- | --- | --- |
| SkillMedev/educators-toolkit | 6 项教师工作流，课程安排、备课、分层、测验、量规与反馈 | 采用全部 6 项方法并做中文适配 |
| bstellato/ai-teaching-skills | 3 项学习者推理与互教技能 | 采用逐步引导、解答对照与角色互教 |
| yugash007/edu-agent-skills | 20 项学习技能，另有技能模板 | 采用错因诊断、间隔复习、回忆卡与编程调试辅导 |
| learning-commons-org/agent-skills | 4 项 K–12 备课、分层和理解检查技能，Apache-2.0 | 作为对照；本轮优先选择适合大学课程、依赖较少的流程 |
| GarethManning/education-agent-skills | 165 项课程、评价、提问与学习科学技能，CC BY-SA 4.0 | 用于方向调研，本轮未复制其材料 |
| mprokopov/teaching-skills | 先修技能图与课前准备诊断，MIT | 作为后续课程图谱与入学诊断参考 |

来源与本次固定提交如下。

- [Educator's Toolkit](https://github.com/SkillMedev/educators-toolkit/tree/82b4a73c6b4347cc1ce71dc6a6a050a9a6c37504)
- [AI Teaching Skills](https://github.com/bstellato/ai-teaching-skills/tree/6d3f85726e7b0fedacc8a078e174161293777044)
- [Edu Agent Skills](https://github.com/yugash007/edu-agent-skills/tree/e75f44303570bb2eae37a8f7536c0358be2502ee)
- [Learning Commons](https://github.com/learning-commons-org/agent-skills/tree/8b0599c244696d9a8e6978dd58a426f475f37c45)
- [Education Agent Skills Library](https://github.com/GarethManning/education-agent-skills/tree/135d6275e7db0657d70b147f46d3191c5430677d)
- [Course Teaching Skills](https://github.com/mprokopov/teaching-skills/tree/793b1c695252dbe645470330efce5f982d10a626)

## 当前技能

| 方向 | 技能 |
| --- | --- |
| 备课设计 | 课程目标与教学进度、单课教案设计、分层教学与学习支架 |
| 作业测评 | 诊断测验与题目设计、评分量规设计、作业反馈与改进建议、学习数据与测验统计解读 |
| 个别辅导 | 苏格拉底解题引导、参考解答对照学习、费曼讲解与角色互教 |
| 错题复习 | 错因诊断与概念纠偏、间隔复习计划、主动回忆学习卡片 |
| 编程实验 | 编程实验与调试辅导 |
| 资料研读 | 课程资料循证答疑、论文与学术阅读指导 |

选择依据是教学任务是否明确、是否有实际步骤与可观察产物、是否适合中文大学课程，以及能否在当前平台完成。作者对教学方法的表述仅作为设计来源，本轮实际验证覆盖技能加载、代表性对话与脚本执行，后续仍需真实师生反馈。

## 平台适配

当前教学技能位于 `backend/core/teaching_skills/`。每项改编技能的 `SKILL.md` 为中文执行流程，`references/upstream.md` 保留固定版本原文，`ATTRIBUTION.md` 标明改编，`LICENSE` 保留原许可。目录元数据记录仓库、提交、路径与版本。

涉及外部工作区文件、学习记忆和自动提醒的步骤，改为当前对话中可执行的教学流程或可下载建议。平台尚未实现的日程、正式题库发布和最终记分均由技能明确说明边界。纯提示技能只提供技能与参考读取，确实包含脚本的技能才提供脚本执行器。

旧通用开发、部署、设计技能从当前内置目录移除，v0.1.0-baseline 标签保留历史。个人上传技能继续按所有者隔离。旧的 data-analysis、course-retrieval、research-reader 等绑定按相近用途解析为新的教学技能；没有对应项的旧内置绑定不再执行。

## 使用入口

“AI 应用”包含课程循证答疑、教师备课、作业与测评、一对一学习辅导、错题与复习、编程实验辅导、论文与学术阅读、写作反馈八个方向。选择应用后自动绑定对应教学技能，并保留个人上传技能和知识库偏好。技能广场可按教学方向或实际来源筛选，详情中可查看中文流程、上游原文与固定版本来源。
