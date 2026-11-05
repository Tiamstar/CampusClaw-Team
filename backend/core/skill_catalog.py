"""Teaching-focused skills with pinned upstream provenance and lazy resources."""
import json
from pathlib import Path

APPS = [
    {"id": "general", "name": "课程循证答疑", "icon": "▤", "description": "基于课程材料解释概念，给出可回查的依据。", "prompt": "根据问题检索课程资料并解释，区分资料依据和通用知识。", "starter": "请根据课程资料解释一个核心概念，并指出依据", "default_skill_ids": ["course-guide"]},
    {"id": "lesson", "name": "教师备课", "icon": "▦", "description": "从课程目标到教案、分层活动与课堂检查。", "prompt": "帮助教师制定可执行的教案，先对齐学习目标、活动和评价，再安排时间与分层支架。", "starter": "帮我设计一节 50 分钟的课，包含目标、练习和离堂检查", "default_skill_ids": ["lesson-plan-builder", "differentiated-instruction"]},
    {"id": "assessment", "name": "作业与测评", "icon": "✓", "description": "设计诊断题、评分量规和有证据的反馈。", "prompt": "根据本次目标选择出题、量规或反馈技能。结果为教师审核草稿，不直接发布或确定正式成绩。", "starter": "请为本课的学习目标设计诊断题，并附教师版解析", "default_skill_ids": ["quiz-generator", "rubric-builder", "student-feedback-writer"]},
    {"id": "tutor", "name": "一对一学习辅导", "icon": "?", "description": "逐步提示、对照解答或通过讲给 AI 听来检查理解。", "prompt": "先识别用户需要逐步解题、对照已公开解答还是角色互教，每次只采用一种主要辅导模式。", "starter": "我想自己解题，请先问我一个问题定位卡点", "default_skill_ids": ["socratic-tutor", "worked-solution-review", "teach-back"]},
    {"id": "exam", "name": "错题与复习", "icon": "◎", "description": "诊断错因，制作回忆卡片并安排复习。", "prompt": "从具体错误和已有学习证据出发，先修正概念，再设计主动回忆与间隔复习任务。", "starter": "请根据我的错误作答分析错因，再给一道迁移题", "default_skill_ids": ["misconception-detector", "spaced-review", "flashcards"]},
    {"id": "code", "name": "编程实验辅导", "icon": "⌘", "description": "用假设、最小实验和证据理解代码与调试。", "prompt": "围绕学习目标帮助分析代码和报错，指导小步实验；运行结论必须对应实际工具返回。", "starter": "帮我分析一段报错，先明确现象和验证假设", "default_skill_ids": ["programming-tutor"]},
    {"id": "research", "name": "论文与学术阅读", "icon": "◈", "description": "读懂研究问题、方法、证据与局限。", "prompt": "依据实际提供的论文或教材进行结构导读，解释推理并提出阅读问题，不编造实验和引文。", "starter": "请带我读懂材料中的研究问题、论证与局限", "default_skill_ids": ["academic-reading"]},
    {"id": "writing", "name": "写作反馈", "icon": "✎", "description": "对已有文字和项目报告给出可执行的修改建议。", "prompt": "结合任务要求和实际文本给学习反馈，让学习者理解修改理由并保留自己的表达。", "starter": "请根据任务要求反馈我的初稿，指出一项最优先的改进", "default_skill_ids": ["student-feedback-writer", "rubric-builder"]},
]

LEGACY_SKILL_IDS = {
    "course-retrieval": "course-guide", "data-analysis": "learning-analytics",
    "research-reader": "academic-reading", "academic-writing": "student-feedback-writer",
    "study-plan": "spaced-review", "math-hints": "socratic-tutor",
    "systematic-debugging": "programming-tutor", "test-driven-development": "programming-tutor",
    "code-review": "programming-tutor", "codex-jupyter-notebook": "programming-tutor",
}

_ROOT = Path(__file__).with_name("teaching_skills")
BUILTIN_SKILLS = []
for metadata in json.loads((_ROOT / "catalog.json").read_text(encoding="utf-8")):
    folder = _ROOT / metadata["id"]
    resources = {path.relative_to(folder).as_posix(): path.read_text(encoding="utf-8")
                 for directory in (folder / "references", folder / "scripts") if directory.exists()
                 for path in sorted(directory.rglob("*")) if path.is_file()}
    BUILTIN_SKILLS.append({**metadata, "builtin": True,
        "instructions": (folder / "SKILL.md").read_text(encoding="utf-8"),
        "resources": resources,
        "requirements": "使用已提供的学习材料与实际证据；正式成绩和发布由教师确认。",
        "runtime_note": "中文版为本平台的执行流程，上游原文供按需核对。复习安排以建议输出，当前不会自动创建日程。"})
