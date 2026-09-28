"""Discover and retrieve a small, relevant set of images from local data/."""

from __future__ import annotations

import base64
import hashlib
import re
import sqlite3
import threading
import time
from pathlib import Path

from PIL import Image, ImageOps

from importer import DB_PATH


DATA_DIR = Path(__file__).resolve().parent / "data"
PREVIEW_DIR = DATA_DIR / "library_previews"
RASTER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
SOURCE_EXTENSIONS = RASTER_EXTENSIONS | {".psd", ".ai"}
EXCLUDED_FOLDERS = {
    "activity_exports", "activity_files", "articles", "graphic_previews",
    "library_previews", "media", "snapshots",
}
_CACHE_LOCK = threading.Lock()
_CATALOG_CACHE: list[dict] = []
_CATALOG_AT = 0.0


def _safe_file(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(DATA_DIR.resolve()) and path.is_file()
    except OSError:
        return False


def _image_id(path: Path) -> str:
    relative = path.relative_to(DATA_DIR).as_posix()
    return hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]


def _record(path: Path, *, kind: str, label: str, source_url: str = "", article_id: int | None = None) -> dict:
    suffix = path.suffix.lower()
    pdf_compatible_ai = False
    if suffix == ".ai":
        with path.open("rb") as stream:
            pdf_compatible_ai = stream.read(4) == b"%PDF"
    previewable = (suffix in RASTER_EXTENSIONS and path.stat().st_size > 100) or (suffix == ".psd" and path.stat().st_size <= 40_000_000) or pdf_compatible_ai
    return {
        "id": _image_id(path), "path": path, "label": label,
        "relative_path": path.relative_to(DATA_DIR).as_posix(),
        "source_kind": kind, "source_url": source_url,
        "article_id": article_id, "reusable": kind == "library",
        "previewable": previewable,
        "size": path.stat().st_size,
    }


def _curated_records() -> list[dict]:
    records = []
    if not DATA_DIR.is_dir():
        return records
    for folder in DATA_DIR.iterdir():
        if not folder.is_dir() or folder.name in EXCLUDED_FOLDERS:
            continue
        for path in folder.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            # A flattened JPEG/PNG companion is easier to preview and use than
            # re-decoding the same PSD on every request.
            if path.suffix.lower() == ".psd" and any(path.with_suffix(ext).is_file() for ext in RASTER_EXTENSIONS):
                continue
            if _safe_file(path):
                label = " / ".join([*path.relative_to(DATA_DIR).parts[:-1], path.stem])
                records.append(_record(path, kind="library", label=label))
    return records


def _archive_records() -> list[dict]:
    if not DB_PATH.is_file():
        return []
    records = []
    with sqlite3.connect(DB_PATH, timeout=15) as db:
        rows = db.execute("""SELECT i.local_path, i.image_index, a.id, a.title, a.source_url
            FROM article_images i JOIN articles a ON a.id=i.article_id
            WHERE i.download_status='downloaded' AND i.local_path IS NOT NULL
            ORDER BY a.published_at DESC, i.image_index ASC""").fetchall()
    seen = set()
    for saved_path, index, article_id, title, source_url in rows:
        relative = str(saved_path).replace("\\", "/")
        if relative.startswith("data/"):
            relative = relative[5:]
        path = DATA_DIR / relative
        if not _safe_file(path) or path.suffix.lower() not in RASTER_EXTENSIONS:
            continue
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        records.append(_record(path, kind="archive", label=f"{title} · 第 {index} 张图", source_url=source_url, article_id=article_id))
    return records


def catalog(force: bool = False) -> list[dict]:
    global _CATALOG_CACHE, _CATALOG_AT
    with _CACHE_LOCK:
        if force or not _CATALOG_CACHE or time.monotonic() - _CATALOG_AT > 60:
            _CATALOG_CACHE = _curated_records() + _archive_records()
            _CATALOG_AT = time.monotonic()
        return _CATALOG_CACHE


def _search_terms(query: str) -> list[str]:
    runs = re.findall(r"[\u3400-\u9fff]{2,}|[a-zA-Z0-9]{3,}", query.casefold()[:600])
    terms = []
    for run in runs:
        if len(run) <= 8:
            terms.append(run)
        if re.search(r"[\u3400-\u9fff]", run):
            terms.extend(run[i:i + 2] for i in range(min(len(run) - 1, 35)))
    joined = " ".join(terms)
    for trigger, extra in (("新生", "迎新"), ("迎新", "新生"), ("茶话", "交流"), ("交流", "茶话"), ("建筑", "校园"), ("工学院", "新奥 工小成")):
        if trigger in joined or trigger in query:
            terms.extend(extra.split())
    return list(dict.fromkeys(term for term in terms if term not in {"活动", "策划", "内容", "推送", "图片", "学院"}))


def media_role(record: dict) -> str:
    """Return the intended role of a curated local image.

    The folder names are part of the local media contract.  Keeping this
    classification in the catalog means every downstream agent follows the
    same placement rules instead of guessing from a filename.
    """
    if not record.get("reusable"):
        return "archive_reference"
    top = str(record.get("relative_path", "")).split("/", 1)[0]
    if top == "学校学院":
        return "school_brand"
    if top == "过渡图标":
        return "transition_icon"
    return "general"


def search_images(query: str, limit: int = 12, *, include_unpreviewable: bool = False,
                  include_archive: bool = False, refresh: bool = False) -> list[dict]:
    terms = _search_terms(query)
    scored = []
    for record in catalog(force=refresh):
        # Historical article photos are kept in the archive for reference
        # queries, but are intentionally excluded from the content asset
        # picker unless a caller explicitly asks for them.
        if not include_archive and not record["reusable"]:
            continue
        if not record["previewable"] and not include_unpreviewable:
            continue
        label = record["label"].casefold()
        score = sum((5 if len(term) > 2 else 2) for term in terms if term in label)
        if not terms:
            score = 1 if record["reusable"] else 0
        if score <= 0:
            continue
        if record["reusable"]:
            score += 6
        if record["path"].suffix.lower() in RASTER_EXTENSIONS:
            score += 1
        scored.append((score, record))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["label"], pair[1]["id"]))
    results = []
    article_count: dict[int, int] = {}
    folder_count: dict[str, int] = {}
    for score, record in scored:
        article_id = record["article_id"]
        if article_id is not None and article_count.get(article_id, 0) >= 2:
            continue
        folder = record["relative_path"].split("/", 1)[0] if record["reusable"] else ""
        if folder and folder_count.get(folder, 0) >= 3:
            continue
        if article_id is not None:
            article_count[article_id] = article_count.get(article_id, 0) + 1
        if folder:
            folder_count[folder] = folder_count.get(folder, 0) + 1
        results.append({**record, "score": score, "media_role": media_role(record)})
        if len(results) >= limit:
            break
    return results


def get_image(image_id: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f]{24}", image_id):
        return None
    return next((record for record in catalog() if record["id"] == image_id), None)


def recommended_images(query: str, limit: int = 3) -> list[dict]:
    candidates = search_images(query, limit=20)
    # Prefer one school/college image and one contextual/general image.  The
    # final first/last placement is enforced by the HTML assembler.
    school = [item for item in candidates if item.get("media_role") == "school_brand"]
    other = [item for item in candidates if item.get("media_role") != "school_brand"]
    selected = school[:1] + other[: max(0, limit - 1)]
    return selected[:limit]


def resolve_images(ids: list[str]) -> list[dict]:
    wanted = list(dict.fromkeys(ids))[:4]
    by_id = {record["id"]: record for record in catalog()}
    return [by_id[image_id] for image_id in wanted if image_id in by_id and by_id[image_id]["previewable"] and by_id[image_id]["reusable"]]


def preview_path(record: dict) -> Path:
    path = record["path"]
    if not record["previewable"] or not _safe_file(path):
        raise ValueError("该素材无法生成图片预览")
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    target = PREVIEW_DIR / f"{record['id']}.jpg"
    if target.is_file() and target.stat().st_mtime_ns >= path.stat().st_mtime_ns:
        return target
    if path.suffix.lower() == ".ai":
        import pypdfium2 as pdfium
        document = pdfium.PdfDocument(str(path))
        page = document[0]
        width, height = page.get_size()
        scale = min(1.5, 1280 / max(width, height, 1))
        image = page.render(scale=scale).to_pil()
        page.close()
        document.close()
    else:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).copy()
    try:
        image.thumbnail((1280, 1280))
        if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", rgba.size, "white")
            background.alpha_composite(rgba)
            image = background.convert("RGB")
        else:
            image = image.convert("RGB")
        image.save(target, format="JPEG", quality=82, optimize=True)
    finally:
        image.close()
    return target


def image_data_url(record: dict) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(preview_path(record).read_bytes()).decode("ascii")


def public_record(record: dict) -> dict:
    return {key: record[key] for key in ("id", "label", "relative_path", "source_kind", "source_url", "reusable", "previewable", "score", "media_role") if key in record} | {
        "preview_url": f"/api/library/images/{record['id']}/preview" if record["previewable"] else ""
    }
