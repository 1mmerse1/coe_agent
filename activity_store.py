"""Durable local activity workspaces and their uploaded source files."""

from __future__ import annotations

import base64
import binascii
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PROJECT_DB = DATA_DIR / "activity_projects.sqlite3"
FILES_DIR = DATA_DIR / "activity_files"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _project_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("无效的活动编号") from exc


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(PROJECT_DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS activity_projects (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        stage TEXT NOT NULL DEFAULT 'brainstorm',
        state_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    return db


def _metadata(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in ("id", "title", "stage", "created_at", "updated_at")}


def create_project() -> dict:
    project_id = str(uuid.uuid4())
    now = _now()
    with _connect() as db:
        db.execute(
            "INSERT INTO activity_projects(id,title,stage,state_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (project_id, "未命名活动", "brainstorm", "{}", now, now),
        )
        return _metadata(db.execute("SELECT * FROM activity_projects WHERE id=?", (project_id,)).fetchone())


def list_projects() -> list[dict]:
    with _connect() as db:
        rows = db.execute("SELECT * FROM activity_projects ORDER BY updated_at DESC LIMIT 200").fetchall()
    return [_metadata(row) for row in rows]


def _save_attachments(project_id: str, state: dict) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    attachments = state.get("attachments") or {}
    if not isinstance(attachments, dict):
        return refs
    for stage in ("brainstorm", "planning", "content"):
        items = attachments.get(stage) or []
        if not isinstance(items, list):
            continue
        refs[stage] = []
        for item in items[:12]:
            if not isinstance(item, dict):
                continue
            storage_id = str(item.get("storage_id") or "")
            data_url = item.pop("data_url", "") or ""
            if data_url and not storage_id:
                if "," not in data_url or not data_url.lower().startswith("data:"):
                    raise ValueError("附件数据格式有误")
                try:
                    blob = base64.b64decode(data_url.split(",", 1)[1], validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise ValueError("附件数据无法读取") from exc
                if len(blob) > 12_000_000:
                    raise ValueError("单个附件超过 12 MB")
                storage_id = uuid.uuid4().hex
                folder = FILES_DIR / project_id
                folder.mkdir(parents=True, exist_ok=True)
                temporary = folder / f"{storage_id}.tmp"
                temporary.write_bytes(blob)
                os.replace(temporary, folder / storage_id)
            item["storage_id"] = storage_id
            refs[stage].append(storage_id)
    return refs


def save_project(project_id: str, incoming: dict) -> dict:
    project_id = _project_id(project_id)
    state = json.loads(json.dumps(incoming, ensure_ascii=False))
    with _connect() as db:
        if not db.execute("SELECT 1 FROM activity_projects WHERE id=?", (project_id,)).fetchone():
            raise KeyError("活动不存在")
        refs = _save_attachments(project_id, state)
        title = str(state.get("title") or "未命名活动").strip()[:160] or "未命名活动"
        stage = str(state.get("stage") or "brainstorm")
        if stage not in {"brainstorm", "planning", "content"}:
            stage = "brainstorm"
        db.execute(
            "UPDATE activity_projects SET title=?,stage=?,state_json=?,updated_at=? WHERE id=?",
            (title, stage, json.dumps(state, ensure_ascii=False), _now(), project_id),
        )
        meta = _metadata(db.execute("SELECT * FROM activity_projects WHERE id=?", (project_id,)).fetchone())
    return {**meta, "attachment_refs": refs}


def load_project(project_id: str) -> dict:
    project_id = _project_id(project_id)
    with _connect() as db:
        row = db.execute("SELECT * FROM activity_projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise KeyError("活动不存在")
    state = json.loads(row["state_json"])
    attachments = state.get("attachments") or {}
    for items in attachments.values() if isinstance(attachments, dict) else []:
        if not isinstance(items, list):
            continue
        for item in items:
            storage_id = str(item.get("storage_id") or "")
            if not storage_id or not storage_id.isalnum():
                continue
            path = FILES_DIR / project_id / storage_id
            if path.is_file():
                mime = item.get("mime_type") or "application/octet-stream"
                item["data_url"] = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    return {**_metadata(row), "state": state}
