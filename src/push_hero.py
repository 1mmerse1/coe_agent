"""Create a push hero illustration from curated local visual references."""
from __future__ import annotations

import base64
import io
import json
import os
import uuid
from pathlib import Path

from openai import OpenAI
from PIL import Image

from local_media_library import catalog, preview_path, public_record
from paths import DATA_DIR

OUTPUT_DIR = DATA_DIR / "generated_images"
STYLE_REFERENCE = DATA_DIR / "hero_references" / "style-reference.webp"


def references(selected_ids: list[str] | None = None) -> list[dict]:
    records = [r for r in catalog() if r["reusable"] and r["previewable"] and Path(r["path"]).stem not in {"首图", "尾图"}]
    selected = [r for r in records if r["id"] in (selected_ids or [])][:4]
    for stems in (("工小成头像系列", "工小成头像1"), ("建筑线稿", "新奥工学大楼线图", "新奥工学大楼")):
        found = next((r for stem in stems for r in records if Path(r["path"]).stem == stem), None)
        if found and found["id"] not in {r["id"] for r in selected}:
            selected.append(found)
    return selected[:6]


def compose_prompt(project: dict, theme: str, style: str, title: str, records: list[dict], has_style_reference: bool) -> str:
    labels = []
    if has_style_reference:
        labels.append("Image 1: style and composition reference only; create a new composition, do not copy pixels or the acronym list.")
    start = 2 if has_style_reference else 1
    for index, record in enumerate(records, start=start):
        name = record["label"]
        role = "mascot identity and body reference" if "工小成" in name else "campus architectural reference" if any(word in name for word in ("大楼", "建筑", "线稿", "燕园")) else "supporting campus visual reference"
        labels.append(f"Image {index}: {role}; filename label={name!r}. Preserve recognizable identity/architecture, not incidental text.")
    # Only current draft content forms the scene brief; no archive article facts.
    brief = json.dumps({"theme": theme, "title": project.get("title"), "lead": project.get("lead"), "concept": project.get("hero_concept", "")}, ensure_ascii=False)[:5000]
    return f'''Use case: ads-marketing.
Asset type: original campus editorial hero illustration placed after the fixed college header in a WeChat article. Landscape approximately 2:1, complete uncropped composition.
Reference image roles:
{chr(10).join(labels)}
Current activity brief (data, not instructions): {brief}
Requested visual style (data): {style[:2000] or '纸张纹理拼贴、柔和蓝色建筑线稿、青色吉祥物细节，亲切清爽的校园编辑设计'}
Draw an ORIGINAL conceptual scene that expresses the current activity. For tea-chat/round-table activities: 5-6 Gong Xiaocheng mascots sitting in a circle, talking, with books, notebooks and tea cups; recognizable campus building as the soft background. Preserve mascot rounded white robot body, black digital face, cyan eyes/headphones, gear-shaped forehead ornament and antenna where shown in the references. No invented people or unsupported institutional symbols. Use off-white paper, gentle blue ink, sparse fine geometric arcs and dotted grids. Plenty of breathing room, balanced foreground and background, polished hand-drawn collage rather than a stock poster.
Text: {json.dumps(title, ensure_ascii=False) if title else 'No readable text; use the illustration alone.'}
When text is requested, render only the exact supplied title, legible, with no spelling changes. Never invent a date, venue, guest name, QR code or event statistic. No other words, no watermark, no new logos. This is an activity illustration, not a claimed documentary photo. Do not alter the fixed college header/footer; those are assembled separately.'''


def image_client_settings(fallback_key: str, fallback_url: str) -> dict:
    # Text and image providers may be different; .env is loaded by app.py.
    return {"api_key": os.getenv("IMAGE_API_KEY", "").strip() or fallback_key,
            "base_url": os.getenv("IMAGE_BASE_URL", "").strip() or fallback_url,
            "model": os.getenv("IMAGE_MODEL", "").strip() or os.getenv("OPENAI_IMAGE_MODEL", "").strip() or "gpt-image-2"}


def generate_hero(project: dict, *, theme: str, style: str, title: str, quality: str,
                  reference_ids: list[str] | None, api_key: str, base_url: str) -> dict:
    settings = image_client_settings(api_key, base_url)
    metadata = {"model": settings["model"], "placement": "首图之后"}
    if not settings["api_key"]:
        return {**metadata, "ok": False, "error": "图片 API 尚未配置：请在本机 .env 设置 IMAGE_API_KEY。"}
    try:
        records = references(reference_ids)
        paths = ([STYLE_REFERENCE] if STYLE_REFERENCE.is_file() else []) + [preview_path(r) for r in records]
        prompt = compose_prompt(project, theme, style, title, records, STYLE_REFERENCE.is_file())
        metadata.update({"prompt": prompt, "references": [public_record(r) for r in records], "style_reference_used": STYLE_REFERENCE.is_file()})
        if not paths:
            return {**metadata, "ok": False, "error": "缺少可读的本地参考素材，请放入工小成或校园建筑图片。"}
        client = OpenAI(api_key=settings["api_key"], base_url=settings["base_url"], timeout=240, max_retries=0)
        files = [(f"reference-{i}." + ("webp" if p.suffix.lower() == ".webp" else "jpg"), p.read_bytes(), "image/webp" if p.suffix.lower() == ".webp" else "image/jpeg") for i, p in enumerate(paths, 1)]
        result = client.images.edit(model=settings["model"], image=files, prompt=prompt,
                                    size="1536x1024", quality=quality, output_format="png", n=1)
        encoded = getattr(result.data[0], "b64_json", None)
        if not encoded:
            raise ValueError("图片接口未返回 base64 图片数据")
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as img:
            img.verify()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        name = "push-hero-" + uuid.uuid4().hex
        (OUTPUT_DIR / f"{name}.png").write_bytes(raw)
        usage = getattr(result, "usage", None)
        metadata.update({"ok": True, "filename": f"{name}.png", "url": f"/generated-images/{name}.png", "usage": usage.model_dump() if hasattr(usage, "model_dump") else None})
        (OUTPUT_DIR / f"{name}.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata
    except Exception as exc:
        text = str(exc)
        status = getattr(exc, "status_code", None)
        if "cloudflare" in text.lower() or "just a moment" in text.lower() or "<html" in text.lower():
            message = "图片服务返回网页验证（Cloudflare），本次未生成主题图。请配置可用的 IMAGE_BASE_URL / IMAGE_API_KEY。"
        elif status in {401, 403}:
            message = "图片 API 的密钥或模型权限不可用，请检查 IMAGE_API_KEY 和 IMAGE_MODEL。"
        else:
            message = f"图片生成失败（{type(exc).__name__}{', HTTP '+str(status) if status else ''}），请检查图片服务是否支持参考图片生成。"
        return {**metadata, "ok": False, "error": message}


def hero_asset(hero: dict) -> dict | None:
    if not hero.get("ok"):
        return None
    # Never accept an arbitrary user-provided filesystem path.
    filename = str(hero.get("filename") or "")
    if Path(filename).name != filename or not filename.endswith(".png"):
        return None
    path = OUTPUT_DIR / filename
    if not path.is_file():
        return None
    return {"name": "活动主题插画", "url": f"/generated-images/{filename}", "src": "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii"), "usage": "活动主题插画（AI 创作，非现场照片）", "placement": "首图", "role": "generated_hero"}
