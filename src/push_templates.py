"""Extract static, reusable presentation components from local article HTML.

Only allowlisted CSS and provenance leave the parser. Archived text, images,
URLs, SVG and executable HTML never become a template or an Agent instruction.
The cache is local data, and can be regenerated without calling a model.
"""
from __future__ import annotations

import colorsys
import hashlib
import json
import re
import sqlite3
import threading
from collections import Counter
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from importer import DB_PATH
from paths import DATA_DIR

VERSION = 1
CACHE_PATH = DATA_DIR / "push_templates" / "catalog.json"
_LOCK = threading.RLock()
_MEMORY: dict = {}
LAYOUT_NAMES = {"label": "色块标签", "bordered": "边框标题", "underline": "线条标题", "centered": "居中标题", "plain": "简洁标题"}
HUE_NAMES = {"blue": "蓝色", "green": "绿色", "orange": "暖橙", "red": "红色", "purple": "紫色", "neutral": "素色"}


def color(value: str) -> str:
    """Canonical opaque CSS colour; flatten alpha onto white for static export."""
    value = str(value).strip().lower()
    names = {"white": "#ffffff", "black": "#000000", "red": "#ff0000", "blue": "#0000ff", "green": "#008000", "gray": "#808080"}
    value = names.get(value, value)
    if re.fullmatch(r"#[0-9a-f]{3}", value):
        return "#" + "".join(ch * 2 for ch in value[1:])
    if re.fullmatch(r"#[0-9a-f]{6}", value):
        return value
    match = re.fullmatch(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)", value)
    if match:
        channels = [float(match[i]) for i in (1, 2, 3)]
        alpha = float(match[4]) if match[4] is not None else 1
        if all(0 <= v <= 255 for v in channels) and 0 < alpha <= 1:
            return "#" + "".join(f"{round(v * alpha + 255 * (1 - alpha)):02x}" for v in channels)
    return ""


def _rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def _chromatic(value: str) -> bool:
    channels = _rgb(value)
    return max(channels) - min(channels) > 24 and min(channels) < 235


def _hue(value: str) -> str:
    if not _chromatic(value):
        return "neutral"
    hue = colorsys.rgb_to_hsv(*(v / 255 for v in _rgb(value)))[0] * 360
    return "red" if hue < 18 or hue >= 345 else "orange" if hue < 68 else "green" if hue < 175 else "blue" if hue < 265 else "purple"


def readable_color(foreground: str, background: str) -> str:
    def luminance(value):
        channels = [v / 255 for v in _rgb(value)]
        return sum(weight * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4) for weight, v in zip((.2126, .7152, .0722), channels))
    foreground, background = color(foreground) or "#3e3e3e", color(background) or "#ffffff"
    a, b = sorted((luminance(foreground), luminance(background)))
    if (b + .05) / (a + .05) >= 4.5:
        return foreground
    return "#ffffff" if luminance(background) < .18 else "#253142"


def _lengths(value: str, maximum: int = 32, percent: bool = False) -> str:
    parts = value.strip().split()
    if not 1 <= len(parts) <= 4:
        return ""
    result = []
    for part in parts:
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(px|em|%)?", part)
        if not match:
            return ""
        num, unit = float(match[1]), match[2] or "px"
        if unit == "%":
            if not percent:
                return ""
            result.append(f"{min(num, 50):g}%")
        else:
            result.append(f"{min(num * (16 if unit == 'em' else 1), maximum):g}px")
    return " ".join(result)


def _border(value: str) -> str:
    colour_match = re.search(r"rgba?\([^)]*\)|#[\da-fA-F]{3,6}\b|\b(?:white|black|red|blue|green|gray)\b", value)
    style_match = re.search(r"\b(solid|dashed|dotted|double)\b", value)
    width_match = re.match(r"\s*(\d+(?:\.\d+)?)(?:px)?\b", value)
    if colour_match and style_match and width_match:
        c = color(colour_match[0])
        width = min(float(width_match[1]), 4)
        if c and width > 0:
            return f"{width:g}px {style_match[1]} {c}"
    return ""


def safe_css(style: str | dict) -> dict[str, str]:
    """A deliberately small CSS vocabulary, suitable for inline WeChat HTML."""
    raw = dict(re.findall(r"(?:^|;)\s*([\w-]+)\s*:\s*([^;]+)", style)) if isinstance(style, str) else dict(style)
    raw = {str(k).lower(): str(v).strip() for k, v in raw.items()}
    result = {}
    for key, value in raw.items():
        parsed = ""
        if key in {"color", "background-color"}:
            parsed = color(value)
        elif key == "background":
            key, parsed = "background-color", color(value)
        elif key in {"padding", "margin", "padding-top", "padding-bottom", "padding-left", "padding-right"}:
            parsed = _lengths(value)
        elif key == "border-radius":
            parsed = _lengths(value, 80, percent=True)
        elif key == "text-align" and value in {"left", "center", "right", "justify"}:
            parsed = value
        elif key == "font-weight" and value in {"bold", "700", "600", "normal", "400"}:
            parsed = value
        elif key in {"font-size", "letter-spacing"}:
            parsed = _lengths(value, 48 if key == "font-size" else 4)
        elif key == "line-height" and re.fullmatch(r"\d+(?:\.\d+)?", value):
            parsed = f"{max(1.4, min(float(value), 2.2)):g}"
        elif key in {"border", "border-top", "border-right", "border-bottom", "border-left"}:
            parsed = _border(value)
        if parsed:
            if key == "border":
                result.update({f"border-{side}": parsed for side in ("top", "right", "bottom", "left")})
            else:
                result[key] = parsed
    # Most Xiumi files express borders as three separate properties.
    styles = raw.get("border-style", "").split()
    widths = (raw.get("border-width", "") or "1px").split()
    colours = re.findall(r"rgba?\([^)]*\)|#[\da-fA-F]{3,6}\b|\b(?:white|black)\b", raw.get("border-color", ""))
    def expand(values):
        return (values * 4)[:4] if len(values) == 1 else [values[0], values[1], values[0], values[1]] if len(values) == 2 else [values[0], values[1], values[2], values[1]] if len(values) == 3 else values[:4]
    if styles and widths and colours:
        for side, w, s, c in zip(("top", "right", "bottom", "left"), expand(widths), expand(styles), expand(colours)):
            parsed = _border(f"{w} {s} {c}")
            if parsed:
                result[f"border-{side}"] = parsed
    return result


def css_text(style: dict) -> str:
    return ";".join(f"{key}:{value}" for key, value in safe_css(style).items()) + ";"


def _decorated(style: dict) -> bool:
    return any(k.startswith("border-") and k != "border-radius" for k in style) or style.get("background-color", "#ffffff") != "#ffffff"


def _mode(values: list[dict]) -> dict:
    if not values:
        return {}
    counts = Counter(json.dumps(value, sort_keys=True) for value in values)
    return json.loads(counts.most_common(1)[0][0])


def extract_profile(row: dict) -> dict:
    soup = BeautifulSoup(row.get("content_html_local") or "", "lxml")
    for node in soup.select("script,style,svg,iframe,object"):
        node.decompose()
    nodes = soup.select("p,h1,h2,h3,h4,li")
    nodes = [node for node in nodes if len(node.get_text(strip=True)) >= 2]
    chars = sum(len(node.get_text(strip=True)) for node in nodes)
    if chars < 120 or len(nodes) < 4:
        return {}  # Pure image articles cannot provide an editable text layout.
    styled = {id(node): safe_css(node.get("style", "")) for node in soup.select("[style]")}
    accents, backgrounds, cards, headings, infos, body_styles = [], [], [], [], [], []
    for node in soup.select("[style]"):
        style = styled[id(node)]
        for key in ("color", "background-color"):
            c = style.get(key)
            if c and _chromatic(c):
                accents.append(c)
        c = style.get("background-color")
        if c and c != "#ffffff" and min(_rgb(c)) > 195:
            backgrounds.append(c)
        length = len(node.get_text(strip=True))
        if 80 <= length <= 1600 and _decorated(style):
            cards.append({k: v for k, v in style.items() if k not in {"color", "font-size", "font-weight", "line-height", "letter-spacing", "text-align", "margin"}})
    for node in nodes:
        text = node.get_text(strip=True)
        chain = [node, *list(node.parents)[:5]]
        inherited = {}
        for ancestor in reversed(chain):
            inherited.update({k: v for k, v in styled.get(id(ancestor), {}).items() if k in {"color", "text-align", "font-size", "line-height", "letter-spacing", "font-weight"}})
        descendant = max(node.select("span,strong,b"), key=lambda n: len(n.get_text(strip=True)), default=None)
        if descendant is not None:
            inherited.update(styled.get(id(descendant), {}))
        bold = node.name.startswith("h") or bool(node.select("strong,b")) or inherited.get("font-weight") in {"bold", "600", "700"}
        large = float(inherited.get("font-size", "16px").replace("px", "")) >= 17
        if 2 <= len(text) <= 28 and (large or bold):
            component = {k: v for k, v in inherited.items() if k in {"color", "text-align"}}
            for ancestor in chain:
                deco = styled.get(id(ancestor), {})
                if _decorated(deco) and len(ancestor.get_text(strip=True)) <= max(100, len(text) * 5):
                    component.update({k: v for k, v in deco.items() if k.startswith("border-") or k in {"background-color", "padding"}})
                    break
            headings.append(component)
        elif len(text) > 35:
            body_styles.append(inherited)
        if any(word in text for word in ("活动时间", "活动地点", "报名方式")):
            for ancestor in chain:
                deco = styled.get(id(ancestor), {})
                if _decorated(deco) and len(ancestor.get_text(strip=True)) < 900:
                    infos.append({k: v for k, v in deco.items() if k.startswith("border-") or k in {"background-color", "padding"}})
                    break
    if not headings and not cards and not accents:
        return {}
    heading = _mode(headings)
    accent = heading.get("color")
    if not accent or not _chromatic(accent):
        accent = Counter(accents).most_common(1)[0][0] if accents else "#244a86"
    card = _mode(cards)
    info = _mode(infos) or card
    background = Counter(backgrounds).most_common(1)[0][0] if backgrounds else "#f7f9fd"
    layout = "label" if heading.get("background-color", "#ffffff") != "#ffffff" else "bordered" if any(k in heading for k in ("border-left", "border-right", "border-top")) else "underline" if "border-bottom" in heading else "centered" if heading.get("text-align") == "center" else "plain"
    if not heading:
        heading = {"color": accent}
    body = _mode(body_styles)
    text_color = readable_color(body.get("color", "#3e3e3e"), "#ffffff")
    family = "card" if _decorated(card) else "flow"
    tags = []
    for label, words in {"通知招募": ("招募", "招新", "报名", "预告", "征稿"), "活动回顾": ("回顾", "收官", "举行", "总结"), "指南介绍": ("攻略", "指南", "介绍", "手册")}.items():
        if any(word in row["title"] for word in words):
            tags.append(label)
    tags = tags or ["校园活动"]
    return {
        "source_id": int(row["id"]), "source_title": row["title"], "source_url": row["source_url"],
        "accent": accent, "text_color": text_color, "body_background": "#ffffff", "card_background": background,
        "line_height": "1.8", "letter_spacing": "2px", "layout": layout, "family": family, "hue": _hue(accent),
        "components": {"heading": heading, "section": card, "lead": card, "info": info},
        "suitable_for": tags, "image_count": len(soup.select("img")), "section_count": len(headings),
        "evidence": {"text_blocks": len(nodes), "heading_candidates": len(headings), "card_candidates": len(cards), "styled_nodes": len(styled)},
        "quality": min(100, 30 + min(len(headings), 6) * 7 + min(len(cards), 5) * 4 + min(len(accents), 10)),
        "adaptations": ["字号、行距、字距和边距统一为学院规范", "背景图、动画及复杂定位转为静态组件", "模板预览使用占位内容"],
    }


def _fingerprint() -> dict:
    if not DB_PATH.is_file():
        return {"version": VERSION, "missing": True}
    files = [DB_PATH, DB_PATH.with_name(DB_PATH.name + "-wal")]
    return {"version": VERSION, "files": [(str(p.resolve()), p.stat().st_size, p.stat().st_mtime_ns) for p in files if p.is_file()]}


def load_catalog(refresh: bool = False) -> dict:
    global _MEMORY
    with _LOCK:
        fingerprint = _fingerprint()
        # JSON normalises tuples to lists.
        fingerprint = json.loads(json.dumps(fingerprint))
        if not refresh and _MEMORY.get("fingerprint") == fingerprint:
            return _MEMORY
        if not refresh and CACHE_PATH.is_file():
            try:
                cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
                if cached.get("fingerprint") == fingerprint:
                    _MEMORY = cached
                    return cached
            except (OSError, ValueError):
                pass
        rows = []
        if DB_PATH.is_file():
            with sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                rows = [dict(r) for r in db.execute("SELECT id,title,source_url,content_html_local FROM articles ORDER BY id")]
        profiles, skipped, groups = [], [], {}
        for row in rows:
            profile = extract_profile(row)
            if not profile:
                skipped.append({"source_id": row["id"], "reason": "可编辑文字或可识别样式不足（可能为图片式推文）"})
                continue
            profiles.append(profile)
            # Counts and article facts do not define a layout. Group by geometry
            # and colour family, retaining source-specific component variants.
            signature = (profile["layout"], profile["family"], profile["hue"])
            groups.setdefault(signature, []).append(profile)
        templates = []
        for signature, members in groups.items():
            representative = max(members, key=lambda item: (item["quality"], -item["source_id"]))
            template = dict(representative)
            template_id = "layout-" + hashlib.sha256("|".join(signature).encode()).hexdigest()[:12]
            template.update({"template_id": template_id, "label": f"{HUE_NAMES[signature[2]]} · {LAYOUT_NAMES[signature[0]]} · {'卡片' if signature[1] == 'card' else '通栏'}", "source_count": len(members), "sources": [{"id": m["source_id"], "title": m["source_title"], "url": m["source_url"]} for m in members], "suitable_for": sorted({tag for m in members for tag in m["suitable_for"]}), "preview_url": f"/api/library/templates/{template_id}/preview"})
            for member in members:
                member["template_id"] = template_id
            templates.append(template)
        templates.sort(key=lambda item: (-item["source_count"], -item["quality"], item["template_id"]))
        _MEMORY = {"fingerprint": fingerprint, "version": VERSION, "extracted_at": datetime.now(timezone.utc).isoformat(), "article_count": len(rows), "usable_articles": len(profiles), "template_count": len(templates), "items": templates, "profiles": profiles, "skipped": skipped}
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = CACHE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(_MEMORY, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(CACHE_PATH)
        return _MEMORY


def catalog(limit: int = 24, query: str = "") -> list[dict]:
    items = list(load_catalog()["items"])
    terms = re.findall(r"[\u4e00-\u9fff]{2,8}|[a-zA-Z]{3,20}", query[:600])
    def rank(item):
        text = " ".join([*item["suitable_for"], *(s["title"] for s in item["sources"])])
        score = sum(term in text for term in terms)
        # Adjacent Chinese bigrams also work when query text has no spaces.
        score += sum(term[i:i + 2] in text for term in terms for i in range(len(term) - 1)) * .1
        return -score, -item["source_count"], -item["quality"]
    items.sort(key=rank)
    return items[:max(1, min(limit, 60))]


def resolve_template(identifier: object) -> dict | None:
    if identifier is None or identifier == "":
        return None
    key = str(identifier)
    data = load_catalog()
    found = next((item for item in data["items"] if item["template_id"] == key), None)
    if found:
        return found
    # Preserve old activity selections and old model responses using source ids.
    key = key.removeprefix("historical-")
    profile = next((p for p in data["profiles"] if str(p["source_id"]) == key), None)
    if profile:
        return next((item for item in data["items"] if item["template_id"] == profile["template_id"]), None)
    return None


def agent_templates(items: list[dict]) -> list[dict]:
    """Small, presentation-only context; raw HTML and past prose are excluded."""
    return [{key: item[key] for key in ("template_id", "source_id", "label", "layout", "family", "accent", "components", "suitable_for", "adaptations")} for item in items]


def render_styles(template: dict | None) -> dict[str, str]:
    """Apply archive decorations while enforcing the college's reading rules."""
    template = template or {}
    accent = color(template.get("accent", "")) or "#244a86"
    bg = color(template.get("card_background", "")) or "#f7f9fd"
    components = template.get("components") or {}
    common = {"font-size": "16px", "line-height": "1.8", "letter-spacing": "2px", "text-align": "justify"}
    heading = {"margin": "18px 0px 6px", "padding": "6px 10px", "color": accent, "text-align": "left"}
    heading.update(safe_css(components.get("heading", {})))
    heading.update({"font-size": "16px", "font-weight": "700", "line-height": "1.8", "letter-spacing": "2px"})
    heading["color"] = readable_color(heading.get("color", accent), heading.get("background-color", "#ffffff"))
    heading["text-align"] = "left" if heading.get("text-align") == "justify" else heading.get("text-align", "left")
    if not _decorated(heading) and heading["text-align"] != "center":
        heading["border-bottom"] = f"2px solid {accent}"
    card = {"margin": "6px 0px 18px", "padding": "12px", "background-color": bg}
    card.update(safe_css(components.get("section", {})))
    # Body containers never inherit heading alignment, size or colour.
    for key in ("font-size", "font-weight", "color", "text-align", "line-height", "letter-spacing"):
        card.pop(key, None)
    flow = template.get("family") == "flow"
    section = {"margin": "0px 0px 18px", "padding": "0px"} if flow else card
    info = {**card, **safe_css(components.get("info", {})), **common}
    info["color"] = readable_color("#3e3e3e", info.get("background-color", "#ffffff"))
    lead = {**card, **safe_css(components.get("lead", {})), **common}
    lead["color"] = readable_color("#3e3e3e", lead.get("background-color", "#ffffff"))
    return {"heading": css_text(heading), "major_heading": css_text({**heading, "font-size": "18px"}), "body": css_text({**common, "margin": "0px 0px 6px", "padding": "0px"}), "section": css_text(section), "lead": css_text(lead), "info": css_text(info), "divider": css_text({"margin": "18px 0px", "border-top": f"1px dashed {accent}"})}


def block_presentation(block: dict, fallback: dict | None, resolved: dict | None = None) -> dict:
    """Resolve each block to plain text or a known archive style, never raw CSS.

    Missing layout keeps existing saved drafts compatible with their template.
    Explicit plain blocks ignore template decoration and retain reading rules.
    """
    layout = block.get("layout") if block.get("layout") in ("plain", "heading", "template") else "template"
    selected = fallback
    identifier = block.get("template_id")
    if layout != "plain" and isinstance(identifier, (str, int)) and identifier:
        key = str(identifier)
        if resolved is not None:
            if key not in resolved:
                resolved[key] = resolve_template(key)
            selected = resolved[key] or fallback
        else:
            selected = resolve_template(key) or fallback
    styles = render_styles(selected)
    if layout == "heading":
        styles["section"] = "margin:0px 0px 18px;padding:0px;"
    if layout == "plain":
        common = {"font-size": "16px", "line-height": "1.8", "letter-spacing": "2px", "text-align": "justify", "color": "#3e3e3e"}
        heading = {**common, "font-weight": "700", "text-align": "left", "margin": "18px 0px 6px", "padding": "0px"}
        prose = css_text({**common, "margin": "6px 0px 18px", "padding": "0px"})
        styles.update({"heading": css_text(heading), "major_heading": css_text({**heading, "font-size": "18px"}),
                       "section": "margin:0px 0px 18px;padding:0px;", "lead": prose, "info": prose})
    return {"layout": layout, "template_id": selected.get("template_id", "") if selected and layout != "plain" else "",
            "label": selected.get("label", "学院默认样式") if selected and layout != "plain" else "普通正文" if layout == "plain" else "学院默认样式",
            "styles": styles}
