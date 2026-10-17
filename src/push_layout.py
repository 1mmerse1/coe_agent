"""Explicit placement of reusable content components and safe table rendering."""
from __future__ import annotations

import html
import re

from push_publication import public_text


def normalize_component_layout(project: dict) -> dict:
    sections = project.get("sections") or []
    raw = project.get("component_layout")
    raw = raw if isinstance(raw, dict) else {}
    clean = {}
    for kind in ("activity_info", "schedule", "guests"):
        item = raw.get(kind)
        if not isinstance(item, dict):
            continue
        index = item.get("section_index")
        if index is not None and (type(index) is not int or not 0 <= index < len(sections)):
            raise ValueError(f"{kind} 指定的板块不存在，原预览保留。")
        if kind == "guests" and index is None:
            continue
        clean[kind] = {"section_index": index}
        if kind == "schedule":
            clean[kind]["format"] = "table" if item.get("format") == "table" else "text"
    project["component_layout"] = clean
    return project


def section_has_components(project: dict, index: int) -> bool:
    return any(isinstance(item, dict) and type(item.get("section_index")) is int and item["section_index"] == index
               for item in (project.get("component_layout") or {}).values())


def apply_placement_request(project: dict, message: str) -> None:
    """Honor explicit numbered placement even if a model omits layout fields."""
    layout = project.setdefault("component_layout", {})
    number = r"([0-9一二三四五六七八九十两]{1,2})"
    numerals = {"一":1,"二":2,"两":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10}
    # Each clause has its own component scope, e.g. information in part 1;
    # guests in part 2. Never infer guest placement from module prose.
    for clause in re.split(r"[；;。,，\n]", message):
        match = re.search(r"(?:放|移|归|集中|安排|置)[^；;。\n]{0,20}?第\s*" + number + r"\s*(?:个)?(?:部分|板块|模块)", clause)
        if match:
            raw = match.group(1)
            index = (int(raw) if raw.isdigit() else numerals.get(raw, 0)) - 1
            kinds = []
            if re.search(r"活动信息|时间.*地点|具体时间|活动时间", clause):
                kinds.append("activity_info")
            if re.search(r"时间安排|流程|具体时间", clause):
                kinds.append("schedule")
            if "嘉宾" in clause:
                kinds.append("guests")
            for kind in kinds:
                layout[kind] = {**layout.get(kind, {}), "section_index": index}
    if re.search(r"(?:时间安排|流程)[^；;。\n]{0,18}(?:表格|表呈现|表展示)", message):
        layout["schedule"] = {**layout.get("schedule", {}), "format": "table"}
    normalize_component_layout(project)
    target = (project["component_layout"].get("guests") or {}).get("section_index")
    if type(target) is int:
        for section in project.get("sections") or []:
            section.pop("guest_indices", None)
        project["sections"][target]["guest_indices"] = list(range(len(project.get("guest_cards") or [])))


def schedule_rows(value: str) -> list[list[str]]:
    rows = []
    for raw in str(value or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if "|" in line:
            cells = [s.strip() for s in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", s) for s in cells):
                continue
            if cells[0] in {"时间", "时段"}:
                continue
            rows.append(cells[:1] + [" / ".join(cells[1:])])
            continue
        match = re.match(r"^\s*(\d{1,2}[:：]\d{2}(?:\s*(?:—+|–|-|~|～|至)\s*\d{1,2}[:：]\d{2})?)\s*[｜|、]?\s*(.*)$", line)
        rows.append([match.group(1), match.group(2)] if match else ["", line])
    return [[public_text(cell) for cell in row] for row in rows if any(public_text(cell) for cell in row)]


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    """All content escaped; no model HTML or executable attributes accepted."""
    def cells(values, tag):
        return "".join(f'<{tag} style="border:1px solid #dbe4f0;padding:9px 12px;text-align:left;vertical-align:top;word-break:break-word;">{inline_text(v)}</{tag}>' for v in values)
    head = f'<thead><tr style="background:#edf3fb;color:#304c75;">{cells(headers, "th")}</tr></thead>'
    body = "".join(f'<tr style="background:{"#ffffff" if i % 2 == 0 else "#f8faff"};">{cells(row, "td")}</tr>' for i, row in enumerate(rows))
    return f'<table style="width:100%;border-collapse:collapse;border-spacing:0;font-size:15px;line-height:1.7;letter-spacing:1px;margin:12px 0;">{head}<tbody>{body}</tbody></table>'


def inline_text(value: object) -> str:
    text = html.escape(str(value or ""), quote=True)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return text.replace("\n", "<br>")


def render_body(value: str, style: str) -> str:
    """Paragraphs and Markdown pipe tables use the same export renderer."""
    lines = str(value or "").splitlines()
    parts, paragraph = [], []
    def flush():
        if paragraph:
            parts.append(f'<p style="{html.escape(style, quote=True)}">{inline_text(chr(10).join(paragraph))}</p>')
            paragraph.clear()
    index = 0
    while index < len(lines):
        line = lines[index]
        if index + 1 < len(lines) and "|" in line and re.fullmatch(r"\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*", lines[index + 1]):
            flush()
            headers = [s.strip() for s in line.strip().strip("|").split("|")]
            rows = []
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                row = [s.strip() for s in lines[index].strip().strip("|").split("|")]
                rows.append((row + [""] * len(headers))[:len(headers)])
                index += 1
            parts.append(render_table(headers, rows))
            continue
        if not line.strip():
            flush()
        elif line.strip() == "---":
            flush()
            parts.append('<hr style="border:0;border-top:1px solid #dbe4f0;margin:18px 0;">')
        else:
            paragraph.append(line)
        index += 1
    flush()
    return "".join(parts)
