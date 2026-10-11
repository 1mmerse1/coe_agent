"""Export the read-only archive and a selected media set for another install.

The Git repository contains application code only.  This script creates a
portable data directory with the complete historical push database and the
small set of reusable image folders chosen by the team.  It deliberately
doesn't copy API keys, generated previews, activity uploads, or generated
documents.

Examples (PowerShell)::
    python src/export_shared_bundle.py --output .\\shared_bundle
    python src/export_shared_bundle.py --output D:\\coe_shared --folder 学校学院 --folder 过渡图标
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


from paths import DATA_DIR, ROOT_DIR


ROOT = ROOT_DIR
DATA = DATA_DIR
DEFAULT_FOLDERS = ("学校学院", "过渡图标")
ARCHIVE_FILES = ("articles.sqlite3",)
ARCHIVE_DIRS = ("media", "articles")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_path(source: Path, destination: Path) -> list[dict]:
    records: list[dict] = []
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        records.append({"path": destination.name, "bytes": destination.stat().st_size, "sha256": sha256(destination)})
        return records
    if not source.is_dir():
        return records
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        relative = item.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        records.append({"path": str(target.relative_to(destination.parent)).replace("\\", "/"), "bytes": target.stat().st_size, "sha256": sha256(target)})
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="导出可共享的历史推送数据库和指定图片素材")
    parser.add_argument("--output", required=True, type=Path, help="输出目录")
    parser.add_argument("--folder", action="append", dest="folders", help="要共享的 data/ 图片文件夹，可重复指定")
    args = parser.parse_args()
    folders = tuple(args.folders or DEFAULT_FOLDERS)
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    manifest: dict = {
        "format": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contents": [],
        "included_media_folders": list(folders),
        "excluded": [".env", "activity_files", "activity_exports", "graphic_previews", "library_previews", "snapshots"],
    }
    for name in ARCHIVE_FILES:
        manifest["contents"].extend(copy_path(DATA / name, output / "data" / name))
    for name in ARCHIVE_DIRS:
        manifest["contents"].extend(copy_path(DATA / name, output / "data" / name))
    for name in folders:
        source = DATA / name
        if not source.is_dir():
            raise SystemExit(f"素材文件夹不存在：{source}")
        manifest["contents"].extend(copy_path(source, output / "data" / name))
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已导出到：{output}")
    print(f"文件数：{len(manifest['contents'])}")
    print("把该目录复制到项目根目录后，可直接替换或合并其中的 data/ 目录。")


if __name__ == "__main__":
    main()
