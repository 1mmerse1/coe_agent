#!/usr/bin/env python3
"""将微信公众号文章链接导入本地 SQLite 文件及文章素材目录。"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import mimetypes
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MEDIA_DIR = DATA_DIR / "media"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
DB_PATH = DATA_DIR / "articles.sqlite3"
CSV_PATH = DATA_DIR / "文章清单.csv"
FAILED_CSV_PATH = DATA_DIR / "本次导入失败链接.csv"
PARSER_VERSION = "wechat-parser-v2"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 MicroMessenger/8.0.50"
)
IMAGE_HOSTS = ("mmbiz.qpic.cn", "mmecoa.qpic.cn", "mmbiz.qlogo.cn", "wx.qlogo.cn", "thirdwx.qlogo.cn")
MAX_IMAGE_BYTES = 20 * 1024 * 1024
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li", "img", "table"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_time(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_db() -> None:
    with connect_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_url TEXT NOT NULL UNIQUE,
                final_url TEXT,
                account_name TEXT,
                title TEXT NOT NULL DEFAULT '',
                author TEXT,
                published_at TEXT,
                summary TEXT,
                cover_image_url TEXT,
                content_html_raw TEXT NOT NULL DEFAULT '',
                content_html_local TEXT NOT NULL DEFAULT '',
                content_text TEXT NOT NULL DEFAULT '',
                blocks_json TEXT NOT NULL DEFAULT '[]',
                parser_version TEXT NOT NULL,
                import_status TEXT NOT NULL,
                import_warnings TEXT NOT NULL DEFAULT '[]',
                snapshot_path TEXT,
                fetched_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS article_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                image_index INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'body',
                original_url TEXT NOT NULL,
                local_path TEXT,
                sha256 TEXT,
                mime_type TEXT,
                byte_size INTEGER,
                width INTEGER,
                height INTEGER,
                download_status TEXT NOT NULL,
                error_message TEXT,
                UNIQUE(article_id, image_index)
            );
            CREATE TABLE IF NOT EXISTS import_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_url TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 1,
                message TEXT,
                article_id INTEGER REFERENCES articles(id),
                started_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_jobs_started ON import_jobs(started_at);
            """
        )


def normalize_url(value: str) -> str:
    raw = value.strip().strip("\ufeff").strip("<>").strip()
    parts = urlsplit(raw)
    if parts.scheme.lower() != "https" or parts.hostname not in {"mp.weixin.qq.com"}:
        raise ValueError("只接受 https://mp.weixin.qq.com/ 开头的文章链接")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k in {"__biz", "mid", "idx", "sn"}]
    return urlunsplit(("https", "mp.weixin.qq.com", parts.path, urlencode(query), ""))


def load_urls(path: Path) -> list[str]:
    content = path.read_text(encoding="utf-8-sig")
    found: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 同时兼容每行一个网址及简单 CSV。
        for item in re.split(r"[,;\t]", line):
            item = item.strip().strip('"').strip("'")
            if "mp.weixin.qq.com/" in item:
                found.append(item)
                break
    return found


def meta_content(soup: BeautifulSoup, key: str) -> str | None:
    node = soup.find("meta", attrs={"property": key})
    if node is None:
        node = soup.find("meta", attrs={"name": key})
    value = node.get("content", "").strip() if node else ""
    return value or None


def script_value(html: str, names: tuple[str, ...]) -> str | None:
    for name in names:
        patterns = (
            rf"[\"']{re.escape(name)}[\"']\s*:\s*[\"']([^\"']*)[\"']",
            rf"\b{re.escape(name)}\s*=\s*[\"']([^\"']*)[\"']",
        )
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return match.group(1)
    return None


def parse_publish_time(html: str, soup: BeautifulSoup) -> str | None:
    visible = soup.select_one("#publish_time")
    if visible and visible.get_text(strip=True):
        value = visible.get_text(" ", strip=True)
        for fmt in ("%Y年%m月%d日 %H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone(timedelta(hours=8))).isoformat()
            except ValueError:
                pass
    stamp = script_value(html, ("ct", "publish_time"))
    if stamp and stamp.isdigit():
        try:
            return datetime.fromtimestamp(int(stamp), tz=timezone.utc).isoformat(timespec="seconds")
        except (ValueError, OSError, OverflowError):
            return None
    return None


def block_kind(tag: Tag) -> str:
    name = tag.name.lower()
    return {
        "p": "paragraph", "h1": "heading", "h2": "heading", "h3": "heading",
        "h4": "heading", "h5": "heading", "h6": "heading", "img": "image",
        "li": "list_item", "blockquote": "quote", "table": "table",
    }.get(name, "unknown")


def collect_blocks(root: Tag) -> list[dict]:
    blocks: list[dict] = []

    def walk(node: Tag | NavigableString) -> None:
        if isinstance(node, NavigableString):
            text = " ".join(str(node).split())
            if text:
                blocks.append({"type": "paragraph", "text": text, "html": str(node)})
            return
        if not isinstance(node, Tag):
            return
        if node.name in BLOCK_TAGS:
            text = " ".join(node.get_text(" ", strip=True).split())
            block = {"type": block_kind(node), "text": text, "html": str(node)}
            if node.name == "img":
                block["image_url"] = node.get("data-src") or node.get("src") or ""
            blocks.append(block)
            return
        for child in node.children:
            walk(child)

    for child in root.children:
        walk(child)
    return blocks


def get_image_url(img: Tag) -> str | None:
    for attr in ("data-src", "src", "data-original", "data-lazy-src"):
        value = img.get(attr)
        if value and not str(value).startswith("data:"):
            return str(value)
    return None


def is_allowed_image(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in IMAGE_HOSTS)


def download_image(url: str) -> dict:
    if not is_allowed_image(url):
        return {"ok": False, "error": "图片域名不在允许列表中"}
    try:
        with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=(8, 20), stream=True) as response:
            response.raise_for_status()
            mime = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if not mime.startswith("image/"):
                return {"ok": False, "error": f"返回内容不是图片（{mime or '未知类型'}）"}
            chunks = bytearray()
            for chunk in response.iter_content(64 * 1024):
                if chunk:
                    chunks.extend(chunk)
                    if len(chunks) > MAX_IMAGE_BYTES:
                        return {"ok": False, "error": "图片超过 20 MB，已跳过"}
        data = bytes(chunks)
        digest = hashlib.sha256(data).hexdigest()
        ext = mimetypes.guess_extension(mime) or ".img"
        if ext == ".jpe":
            ext = ".jpg"
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        target = MEDIA_DIR / f"{digest}{ext}"
        if not target.exists():
            target.write_bytes(data)
        width = height = None
        try:
            from io import BytesIO
            from PIL import Image
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
        except Exception:
            pass
        return {"ok": True, "sha256": digest, "path": str(target.relative_to(ROOT)),
                "mime": mime, "size": len(data), "width": width, "height": height}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


def parse_article(html: str, final_url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("#js_content")
    if not body:
        raise ValueError("页面里没有找到文章正文区域（#js_content）")

    raw_body = body.decode_contents()
    content_text = body.get_text("\n", strip=True)
    content_text = re.sub(r"\n{3,}", "\n\n", content_text).strip()
    images: list[dict] = []
    for index, img in enumerate(body.find_all("img"), start=1):
        url = get_image_url(img)
        images.append({"index": index, "url": url, "tag": img})
    return {
        "final_url": final_url,
        "title": meta_content(soup, "og:title") or script_value(html, ("msg_title", "title")) or "",
        "account_name": (soup.select_one("#js_name").get_text(" ", strip=True)
                         if soup.select_one("#js_name") else None)
                         or script_value(html, ("nickname", "nick_name", "ori_name", "account_name")),
        "author": meta_content(soup, "author") or script_value(html, ("author", "msg_author")),
        "published_at": parse_publish_time(html, soup),
        "summary": meta_content(soup, "og:description"),
        "cover_image_url": meta_content(soup, "og:image"),
        "content_html_raw": raw_body,
        "content_html_local": "",
        "content_text": content_text,
        "blocks": collect_blocks(body),
        "images": images,
        "body": body,
    }


def save_snapshot(job_id: int, content: bytes) -> str:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"job-{job_id}.html.gz"
    with gzip.open(path, "wb", compresslevel=6) as out:
        out.write(content)
    return str(path.relative_to(ROOT))


def create_job(url: str) -> int:
    with connect_db() as db:
        cur = db.execute(
            "INSERT INTO import_jobs(source_url,status,attempts,started_at) VALUES(?,?,1,?)",
            (url, "fetching", now_iso()),
        )
        return int(cur.lastrowid)


def update_job(job_id: int, status: str, message: str | None = None, article_id: int | None = None) -> None:
    with connect_db() as db:
        db.execute(
            "UPDATE import_jobs SET status=?,message=?,article_id=?,finished_at=? WHERE id=?",
            (status, message, article_id, now_iso(), job_id),
        )


def import_one(raw_url: str) -> tuple[str, str]:
    try:
        url = normalize_url(raw_url)
    except ValueError as exc:
        return "failed", f"链接无效：{exc}"

    cached_images: dict[str, dict] = {}
    with connect_db() as db:
        old = db.execute(
            "SELECT id,import_status,title,parser_version,import_warnings FROM articles WHERE source_url=?", (url,)
        ).fetchone()
        if old and old["parser_version"] == PARSER_VERSION and old["import_status"] in {"completed", "partial"}:
            old_warnings = json.loads(old["import_warnings"] or "[]")
            can_retry = any("未下载" in warning or "没有可下载地址" in warning for warning in old_warnings)
            if old["import_status"] == "completed" or not can_retry:
                return "skipped", f"已导入过：{old['title'] or url}"
        if old:
            for row in db.execute(
                "SELECT original_url,local_path,sha256,mime_type,byte_size,width,height FROM article_images "
                "WHERE article_id=? AND download_status='downloaded'", (old["id"],)
            ):
                cached_images[row["original_url"]] = {
                    "ok": True, "path": row["local_path"], "sha256": row["sha256"], "mime": row["mime_type"],
                    "size": row["byte_size"], "width": row["width"], "height": row["height"],
                }

    job_id = create_job(url)
    try:
        response = requests.get(
            url, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
            timeout=(10, 35), allow_redirects=True,
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        html = response.text
        snapshot_path = save_snapshot(job_id, response.content)
        article = parse_article(html, response.url)
        if not article["title"]:
            raise ValueError("找到了正文，但没有识别出标题；请检查文章页面结构")

        warnings: list[str] = []
        if not article["content_text"]:
            warnings.append("正文没有可提取的文字，可能是整篇内容都排在图片中")
        urls_to_download: list[tuple[int, str]] = []
        for image in article["images"]:
            if image["url"] and image["url"] not in cached_images:
                urls_to_download.append((image["index"], urljoin(response.url, image["url"])))
            elif image["url"]:
                continue
            else:
                warnings.append(f"第 {image['index']} 张图片没有可下载地址")

        downloaded: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(download_image, image_url): idx for idx, image_url in urls_to_download}
            for future in as_completed(futures):
                downloaded[futures[future]] = future.result()

        image_rows: list[dict] = []
        for image in article["images"]:
            original_url = image["url"] or ""
            result = cached_images.get(original_url) or downloaded.get(image["index"], {"ok": False, "error": "没有图片地址"})
            if result.get("ok"):
                image["tag"]["src"] = "/media/" + Path(result["path"]).name
                image["tag"].attrs.pop("data-src", None)
                image_rows.append({"index": image["index"], "original_url": original_url,
                                   "status": "downloaded", **result})
            else:
                image_rows.append({"index": image["index"], "original_url": original_url,
                                   "status": "failed", "error": result.get("error")})
                warnings.append(f"第 {image['index']} 张图片未下载：{result.get('error')}")

        # 从解析树中重新取正文，避免返回 BeautifulSoup 节点到数据库层。
        soup_again = BeautifulSoup(html, "lxml")
        body_local = soup_again.select_one("#js_content")
        assert body_local is not None
        for img, image_info in zip(body_local.find_all("img"), article["images"]):
            result = downloaded.get(image_info["index"], {})
            if result.get("ok"):
                img["src"] = "/media/" + Path(result["path"]).name
                img.attrs.pop("data-src", None)
        article["content_html_local"] = body_local.decode_contents()
        article["blocks"] = collect_blocks(body_local)
        status = "partial" if warnings else "completed"

        with connect_db() as db:
            existing = db.execute("SELECT id,created_at FROM articles WHERE source_url=?", (url,)).fetchone()
            values = (
                url, article["final_url"], article["account_name"], article["title"], article["author"],
                article["published_at"], article["summary"], article["cover_image_url"],
                article["content_html_raw"], article["content_html_local"], article["content_text"],
                json.dumps(article["blocks"], ensure_ascii=False), PARSER_VERSION, status,
                json.dumps(warnings, ensure_ascii=False), snapshot_path, now_iso(),
            )
            if existing:
                article_id = int(existing["id"])
                db.execute("DELETE FROM article_images WHERE article_id=?", (article_id,))
                db.execute(
                    """UPDATE articles SET source_url=?,final_url=?,account_name=?,title=?,author=?,published_at=?,
                    summary=?,cover_image_url=?,content_html_raw=?,content_html_local=?,content_text=?,blocks_json=?,
                    parser_version=?,import_status=?,import_warnings=?,snapshot_path=?,fetched_at=?,updated_at=? WHERE id=?""",
                    (*values, now_iso(), article_id),
                )
            else:
                cur = db.execute(
                    """INSERT INTO articles(source_url,final_url,account_name,title,author,published_at,summary,
                    cover_image_url,content_html_raw,content_html_local,content_text,blocks_json,parser_version,
                    import_status,import_warnings,snapshot_path,fetched_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*values, now_iso(), now_iso()),
                )
                article_id = int(cur.lastrowid)
            for row in image_rows:
                db.execute(
                    """INSERT INTO article_images(article_id,image_index,original_url,local_path,sha256,mime_type,
                    byte_size,width,height,download_status,error_message) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (article_id, row["index"], row["original_url"], row.get("path"), row.get("sha256"),
                     row.get("mime"), row.get("size"), row.get("width"), row.get("height"), row["status"], row.get("error")),
                )
        write_article_files(article_id, article)
        update_job(job_id, status, f"{len(image_rows)} 张图，{len(warnings)} 条提醒", article_id)
        return status, f"{article['title']}（图片 {sum(x['status']=='downloaded' for x in image_rows)}/{len(image_rows)} 张）"
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        update_job(job_id, "failed", message)
        return "failed", message


def write_article_files(article_id: int, article: dict) -> None:
    """写一份可双击预览的文章 HTML 和纯文本副本。"""
    article_dir = DATA_DIR / "articles"
    article_dir.mkdir(parents=True, exist_ok=True)
    body = article["content_html_local"].replace('src="/media/', 'src="../media/')
    html_doc = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(article["title"])}</title>'
        '<style>body{max-width:760px;margin:24px auto;padding:0 16px;font-family:system-ui,"Microsoft YaHei",sans-serif}'
        'img{max-width:100%;height:auto}</style></head><body>' + body + '</body></html>'
    )
    (article_dir / f"{article_id}.html").write_text(html_doc, encoding="utf-8")
    (article_dir / f"{article_id}.txt").write_text(article["content_text"], encoding="utf-8")


def export_csv() -> int:
    initialize_db()
    with connect_db() as db:
        rows = db.execute(
            """SELECT id,title,account_name,author,published_at,source_url,import_status,
            (SELECT count(*) FROM article_images i WHERE i.article_id=a.id AND i.download_status='downloaded') AS saved_images,
            (SELECT count(*) FROM article_images i WHERE i.article_id=a.id) AS total_images,
            import_warnings,content_text FROM articles a ORDER BY published_at DESC,id DESC"""
        ).fetchall()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["文章ID", "标题", "本地预览", "公众号", "作者", "发布时间", "原文链接", "导入状态",
                         "已保存图片", "图片总数", "提醒", "正文文本"])
        for row in rows:
            writer.writerow([row["id"], row["title"], f"articles/{row['id']}.html", row["account_name"], row["author"], local_time(row["published_at"]),
                             row["source_url"], row["import_status"], row["saved_images"], row["total_images"],
                             row["import_warnings"], row["content_text"]])
    return len(rows)


def export_failed_jobs(first_job_id: int) -> int:
    """Keep failed links and reasons in a spreadsheet-friendly file."""
    with connect_db() as db:
        rows = db.execute(
            """SELECT id,source_url,message,started_at FROM import_jobs
            WHERE id>=? AND status='failed' ORDER BY id""",
            (first_job_id,),
        ).fetchall()
    with FAILED_CSV_PATH.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["任务编号", "文章链接", "失败原因", "处理时间"])
        for row in rows:
            writer.writerow([row["id"], row["source_url"], row["message"], row["started_at"]])
    return len(rows)


def show_jobs() -> None:
    initialize_db()
    with connect_db() as db:
        rows = db.execute(
            """SELECT j.id,j.status,j.source_url,j.message,a.title FROM import_jobs j
            LEFT JOIN articles a ON a.id=j.article_id ORDER BY j.id DESC LIMIT 30"""
        ).fetchall()
    if not rows:
        print("还没有导入记录。")
        return
    for row in rows:
        label = row["title"] or row["message"] or row["source_url"]
        print(f"#{row['id']:>3}  {row['status']:<10} {label}")


def main() -> int:
    parser = argparse.ArgumentParser(description="把公众号文章保存到本地文章库")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd_import = sub.add_parser("import", help="导入一个网址文件里的文章")
    cmd_import.add_argument("file", nargs="?", default="推送URL_test.txt", help="每行一条文章链接的文本文件")
    sub.add_parser("list", help="查看最近的导入结果")
    sub.add_parser("export", help="生成可用 Excel 打开的文章清单")
    args = parser.parse_args()
    initialize_db()

    if args.command == "import":
        path = Path(args.file)
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            print(f"找不到链接文件：{path}", file=sys.stderr)
            return 2
        urls = load_urls(path)
        if not urls:
            print("文件里没有找到公众号文章链接。", file=sys.stderr)
            return 2
        print(f"读到 {len(urls)} 条链接，开始导入。重复且已成功的文章会自动跳过。\n")
        with connect_db() as db:
            first_job_id = int(db.execute("SELECT coalesce(max(id),0)+1 FROM import_jobs").fetchone()[0])
        counts = {"completed": 0, "partial": 0, "failed": 0, "skipped": 0}
        for index, url in enumerate(urls, start=1):
            status, message = import_one(url)
            counts[status] = counts.get(status, 0) + 1
            print(f"[{index}/{len(urls)}] {status}: {message}", flush=True)
            time.sleep(0.4)
        total = export_csv()
        failure_count = export_failed_jobs(first_job_id)
        print(f"\n完成：成功 {counts['completed']}，部分成功 {counts['partial']}，失败 {counts['failed']}，跳过 {counts['skipped']}。")
        print(f"文章清单：{CSV_PATH}")
        if failure_count:
            print(f"失败链接及原因：{FAILED_CSV_PATH}")
        print(f"本地文章库：{DB_PATH}（当前共 {total} 篇）")
        return 1 if counts["failed"] else 0
    if args.command == "list":
        show_jobs()
        return 0
    if args.command == "export":
        total = export_csv()
        print(f"已更新文章清单：{CSV_PATH}（{total} 篇）")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
