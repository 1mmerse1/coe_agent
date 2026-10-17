"""Keep unresolved facts in reviewer notes, outside reader-facing push copy."""
from __future__ import annotations

from copy import deepcopy
import re


UNRESOLVED = re.compile(
    r"待确认|未确认|尚未确认|尚未确定|待确定|待定|待补充|待填写|待提供|待核实|待审核|待上传|待插入|未提供|未填写|"
    r"拟定|拟使用|拟邀请|拟聚焦|拟于|拟以|拟在|拟通过|拟安排|拟开展|暂定|暂拟|预计|"
    r"[\[【（(]\s*(?:拟定|建议|缺失|未知|不确定|uncertain|missing|TBD|TBC)[^\]】）)]*[\]】）)]|\b(?:TBD|TBC)\b",
    re.IGNORECASE,
)


def _sentences(line: str) -> list[str]:
    """Keep bracketed annotations together, including their punctuation."""
    closing = {"[": "]", "【": "】", "（": "）", "(": ")"}
    stack: list[str] = []
    parts = []
    start = 0
    for index, char in enumerate(line):
        if char in closing:
            stack.append(closing[char])
        elif stack and char == stack[-1]:
            stack.pop()
        if char in "。！？!?" and not stack:
            parts.append(line[start:index + 1])
            start = index + 1
    if start < len(line):
        parts.append(line[start:])
    return parts


def public_text(value: object, notes: list[str] | None = None, label: str = "正文") -> str:
    """Omit whole marked sentences; never turn a tentative fact definite.

    Unmarked information still relies on the model respecting source status.
    Splitting retains paragraph breaks and independently confirmed sentences.
    """
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    output = []
    for paragraph in re.split(r"\n\s*\n", str(value or "")):
        lines = []
        for line in paragraph.splitlines():
            sentences = _sentences(line)
            kept = []
            for sentence in sentences:
                if UNRESOLVED.search(sentence):
                    if notes is not None:
                        notes.append(f"{label}已省略：{sentence.strip()}")
                else:
                    kept.append(sentence)
            text = "".join(kept).strip()
            if text and not re.fullmatch(r"[\s\[\]【】（）：:、,，—\-•·]+", text):
                lines.append(text)
        if lines:
            output.append("\n".join(lines))
    return "\n\n".join(output)


def publication_project(project: dict) -> dict:
    """Return clean visible fields while preserving layout indices and notes."""
    result = deepcopy(project)
    notes = [str(n) for n in result.get("review_notes", []) if n] if isinstance(result.get("review_notes"), list) else []
    for field, label in (("title", "标题"), ("lead", "导语"), ("participation", "参与方式"), ("schedule", "具体时间安排")):
        result[field] = public_text(result.get(field), notes, label)
    if UNRESOLVED.search(str(project.get("participation") or "")) and re.fullmatch(
        r"\s*(?:第[^\n｜|]{1,12}[部分章节]\s*[｜|：:]?\s*)?(?:报名问卷|报名方式|参与方式|报名入口)\s*",
        result["participation"],
    ):
        result["participation"] = ""
    for index, section in enumerate(result.get("sections", []) if isinstance(result.get("sections"), list) else []):
        if isinstance(section, dict):
            original_heading = str(section.get("heading") or "")
            if UNRESOLVED.search(original_heading):
                notes.append(f"第{index + 1}块已省略：{original_heading}；{section.get('body') or ''}")
                section["heading"] = section["body"] = ""
                section.pop("guest_indices", None)
                continue
            section["heading"] = public_text(original_heading, notes, f"第{index + 1}块标题")
            section["body"] = public_text(section.get("body"), notes, f"第{index + 1}块正文")
    for guest in result.get("guest_cards", []) if isinstance(result.get("guest_cards"), list) else []:
        if isinstance(guest, dict):
            for field in ("name", "identity", "introduction"):
                guest[field] = public_text(guest.get(field), notes, "嘉宾介绍")
    info = result.get("activity_info")
    if isinstance(info, dict):
        for field in ("event_time", "location", "audience"):
            value = info.get(field)
            # A structured fact with a marker is omitted in full.
            if UNRESOLVED.search(str(value or "")):
                notes.append(f"活动信息已省略：{field}：{value}")
                info[field] = ""
    result["review_notes"] = list(dict.fromkeys(notes))
    return result


def publication_notes(project: dict, supplied: dict[str, str]) -> list[str]:
    """Collect missing/omitted fields for the workspace, never for export."""
    notes = list(publication_project(project)["review_notes"])
    for label, value in supplied.items():
        if not str(value or "").strip():
            notes.append(f"{label}尚未提供，已从图文省略；补充确认后再发布。")
        elif UNRESOLVED.search(str(value)):
            notes.append(f"{label}尚未确认，已从图文省略：{value}")
    checks = project.get("checks") if isinstance(project.get("checks"), list) else []
    return list(dict.fromkeys([*notes, *(str(c) for c in checks if c)]))


PUBLICATION_RULES = (
    "成稿规则：标题、导语、正文、活动信息、参与方式和署名只写本次已确认信息。"
    "资料中 status 为 uncertain/missing、标注【未确认】/[待确认]/拟定/建议或尚未核实的具体事实，"
    "应从成稿中省略，不能仅删除标记后保留具体事实，也不能用往期事实补齐。"
    "未知结构化字段返回空字符串，不生成占位文字；某板块没有已确认内容就不写。"
    "正文不得出现未确认、待确认、待补充、TBD等内部标记，也不自行改写为‘敬请期待/另行通知/以通知为准’等承诺。"
    "所有缺失与待核实事项只写在 checks 和 review_notes 数组，供工作台人工审阅，绝不混入图文。"
    "这些成稿规则优先于参考资料中要求显示待确认标记或空白署名的旧规则。"
)
