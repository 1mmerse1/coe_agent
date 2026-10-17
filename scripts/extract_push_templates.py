r"""Rebuild the local historical push layout catalog.

Run from the repository root with ``python -X utf8
scripts/extract_push_templates.py``. The output is local data and is ignored
by Git; collaborators regenerate it from their own shared article database.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from push_templates import load_catalog  # noqa: E402


if __name__ == "__main__":
    data = load_catalog(refresh=True)
    print(json.dumps({key: data[key] for key in ("article_count", "usable_articles", "template_count", "extracted_at")}, ensure_ascii=False, indent=2))
    for item in data["items"]:
        print(f"{item['template_id']}  {item['label']}  ({item['source_count']} 篇)")
