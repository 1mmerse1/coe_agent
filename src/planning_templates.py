"""Planning examples and writing requirements supplied by the user."""

from __future__ import annotations

from paths import TEMPLATE_DIR


TEMPLATES = {
    "detailed": {
        "label": "详细版 · 新生手册类项目",
        "description": "适合跨周项目、内容更新和多阶段交付。重点写实施步骤、质量控制和进度。",
        "sections": ["项目背景与意义", "总体规划", "具体实施方案", "质量控制与成果交付", "进度安排", "资源需求与注意事项"],
    },
    "medium": {
        "label": "中等版 · 大一交流会类活动",
        "description": "适合单次线下活动。重点写活动概要、筹备、现场时间安排和后续工作。",
        "sections": ["活动背景与意义", "活动概要", "具体方案", "资源需求", "注意事项"],
    },
    "concise": {
        "label": "简洁版 · 图书漂流类活动",
        "description": "适合流程清楚的小型活动。用简短概述、安排表、物资和注意事项表达。",
        "sections": ["活动背景与意义", "活动概述", "活动安排", "宣传与资源需求", "注意事项"],
    },
}


def select_template(requested: str, context: str) -> str:
    if requested in TEMPLATES:
        return requested
    text = context.casefold()
    if any(word in text for word in ("手册", "指南", "系列", "长期", "更新项目")):
        return "detailed"
    if any(word in text for word in ("图书漂流", "旧书", "书籍回收", "资料交换")):
        return "concise"
    return "medium"


def template_context(key: str) -> str:
    if key not in TEMPLATES:
        raise ValueError("未知的策划案模板")
    info = TEMPLATES[key]
    sample = (TEMPLATE_DIR / f"{key}.txt").read_text(encoding="utf-8")
    requirements = (TEMPLATE_DIR / "writing_requirements.md").read_text(encoding="utf-8")
    return (
        f"本次策划案类型：{info['label']}\n"
        f"结构建议：{'、'.join(info['sections'])}\n\n"
        f"策划案编写要求（必须遵守，但与用户本次明确事实冲突时以本次事实为准）：\n{requirements}\n\n"
        f"相应历史策划案参考（仅参考篇幅、结构和表达，不得复制其中的时间、人物、地点、预算或其他活动事实）：\n{sample}"
    )


def public_templates() -> list[dict]:
    return [{"key": key, **value} for key, value in TEMPLATES.items()]


def ensure_document_sections(plan: dict, key: str) -> dict:
    """Keep export usable if a model omits the requested document structure."""
    plan["template_type"] = key
    if isinstance(plan.get("document_sections"), list) and plan["document_sections"]:
        return plan

    def value(*fields: str) -> str:
        chunks = []
        for field in fields:
            item = plan.get(field)
            if isinstance(item, list):
                chunks.extend(str(part) for part in item if part)
            elif item:
                chunks.append(str(item))
        return "\n".join(chunks) or "[待确认]"

    mappings = {
        "detailed": [
            ("项目背景与意义", ("objective", "key_message")),
            ("总体规划", ("audience", "promotion_plan")),
            ("具体实施方案", ("workflow", "task_assignments")),
            ("质量控制与成果交付", ("review_checklist",)),
            ("进度安排", ("schedule",)),
            ("资源需求与注意事项", ("materials", "budget_or_resources", "risk_controls")),
        ],
        "medium": [
            ("活动背景与意义", ("objective",)),
            ("活动概要", ("audience", "key_message")),
            ("具体方案", ("schedule", "workflow", "promotion_plan")),
            ("资源需求", ("materials", "budget_or_resources")),
            ("注意事项", ("risk_controls", "open_questions")),
        ],
        "concise": [
            ("活动背景与意义", ("objective",)),
            ("活动概述", ("audience", "key_message")),
            ("活动安排", ("schedule", "workflow")),
            ("宣传与资源需求", ("promotion_plan", "materials", "budget_or_resources")),
            ("注意事项", ("risk_controls", "open_questions")),
        ],
    }
    plan["document_sections"] = [
        {"heading": heading, "body": value(*fields)} for heading, fields in mappings[key]
    ]
    return plan
