"""从 Windows 微信客户端的网页缓存提取工映青春文章链接。

微信客户端打开公众号文章后，会在 radium/web 配置目录的 Share Data 中保留
带访问参数的文章地址。脚本只读取缓存，不修改微信数据。
"""
from __future__ import annotations

import csv
import html
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests


BIZ = "Mzk0NDMzMDM4OQ=="
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/131.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) "
    "WindowsWechat(0x63090a13) UnifiedPCWindows(0xf2541f0d)"
)


def find_share_data() -> list[Path]:
    appdata = Path(os.environ.get("APPDATA", ""))
    root = appdata / "Tencent" / "xwechat" / "radium" / "web" / "profiles"
    result = []
    for path in root.rglob("Share Data"):
        try:
            if BIZ.encode() in path.read_bytes():
                result.append(path)
        except OSError:
            pass
    return result


def extract_signed_urls(path: Path) -> dict[tuple[str, str, str], tuple[str, str]]:
    text = path.read_bytes().decode("utf-8", "ignore")
    text = text.replace("\\/", "/").replace("\\u0026", "&")
    marker = f"https://mp.weixin.qq.com/s?__biz={BIZ}"
    items: dict[tuple[str, str, str], tuple[str, str]] = {}
    start = 0
    while True:
        at = text.find(marker, start)
        if at < 0:
            break
        rest = text[at:]
        stops = [
            pos
            for pos in (
                rest.find("https://", 8),
                rest.find("\x00"),
                rest.find('"'),
                rest.find("<"),
                rest.find(" "),
                rest.find("}"),
            )
            if pos > 0
        ]
        url = rest[: min(stops) if stops else len(rest)]
        previous = text[max(0, at - 120) : at]
        canonical_match = re.search(
            r"https://mp\.weixin\.qq\.com/s/([A-Za-z0-9_-]{16,32})$", previous
        )
        canonical = (
            f"https://mp.weixin.qq.com/s/{canonical_match.group(1)}"
            if canonical_match
            else ""
        )
        query = parse_qs(urlsplit(url).query)
        key = (
            query.get("mid", [""])[0],
            query.get("idx", [""])[0],
            query.get("sn", [""])[0],
        )
        if all(key):
            items[key] = (url, canonical)
        start = at + len(marker)
    return items


def extract_album_urls(path: Path) -> list[str]:
    """Find signed appmsgalbum URLs saved by the WeChat web view."""
    text = path.read_bytes().decode("utf-8", "ignore").replace("\\/", "/")
    marker = f"https://mp.weixin.qq.com/mp/appmsgalbum?__biz={BIZ}"
    result = []
    start = 0
    while True:
        at = text.find(marker, start)
        if at < 0:
            break
        rest = text[at:]
        stops = [
            pos
            for pos in (
                rest.find("https://", 8),
                rest.find("\x00"),
                rest.find('"'),
                rest.find("<"),
                rest.find(" "),
                rest.find("{"),
            )
            if pos > 0
        ]
        url = rest[: min(stops) if stops else len(rest)]
        # Cache records append a JSON object (including the Chinese account
        # name) immediately after the URL. Keep the ASCII URL portion only.
        ascii_url = re.match(r"[\x00-\x7f]+", url)
        if ascii_url:
            url = ascii_url.group(0)
        if "&uin=" in url and url not in result:
            result.append(url)
        start = at + len(marker)
    return result


def album_articles(album_url: str) -> list[tuple[tuple[str, str, str], tuple[str, str]]]:
    """Read all pages of one appmsgalbum using its logged-in client token."""
    headers = {"User-Agent": UA, "Referer": album_url, "X-Requested-With": "XMLHttpRequest"}
    response = requests.get(album_url, headers=headers, timeout=35)
    page = response.text
    album_match = re.search(r"albumId:\s*'([^']+)", page)
    if not album_match:
        return []
    album_id = album_match.group(1)
    # The initial HTML contains the first page as a JavaScript literal.
    item_pattern = re.compile(
        r"title:\s*'((?:\\.|[^'])*)'.*?create_time:\s*'?(\d+).*?"
        r"url:\s*'([^']+)'.*?msgid:\s*'?(\d+).*?itemidx:\s*'?(\d+)",
        re.S,
    )
    found: dict[tuple[str, str, str], tuple[str, str]] = {}

    def add_items(items: list[dict]) -> None:
        for item in items:
            raw_url = html.unescape(str(item.get("url", ""))).replace("http:", "https:")
            query = parse_qs(urlsplit(raw_url).query)
            key = (
                query.get("mid", [str(item.get("msgid", ""))])[0],
                query.get("idx", [str(item.get("itemidx", ""))])[0],
                query.get("sn", [""])[0],
            )
            if all(key) and raw_url:
                found[key] = (raw_url, "")

    initial = []
    for match in item_pattern.finditer(page):
        initial.append(
            {
                "url": match.group(3),
                "msgid": match.group(4),
                "itemidx": match.group(5),
            }
        )
    add_items(initial)
    if not initial:
        return list(found.items())

    last = initial[-1]
    # Album API returns JSON only with f=json. Each request advances from the
    # last message/item pair; continue_flag=0 means the older end was reached.
    for _ in range(200):
        params = (
            f"&count=10&begin_msgid={last['msgid']}&begin_itemidx={last['itemidx']}"
            "&f=json"
        )
        try:
            payload = requests.get(
                album_url + params, headers=headers, timeout=35
            ).json()
            album = payload.get("getalbum_resp", {})
            items = album.get("article_list", []) or []
        except Exception:
            break
        before = len(found)
        add_items(items)
        if not items or len(found) == before or not int(album.get("continue_flag", 0)):
            break
        tail = items[-1]
        last = {"msgid": str(tail.get("msgid", "")), "itemidx": str(tail.get("itemidx", ""))}
        if not last["msgid"]:
            break
    return list(found.items())


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def fetch_article(item: tuple[tuple[str, str, str], tuple[str, str]]) -> dict:
    key, (signed_url, canonical_url) = item
    result = {"key": key, "url": "", "title": "", "published_at": "", "status": "failed"}
    try:
        response = requests.get(
            signed_url,
            headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"},
            timeout=35,
        )
        text = response.text
        # WeChat pages keep the current signed link in msg_link. Related
        # articles may contain other short links, so never take the first
        # /s/<token> occurrence as the current article.
        msg_link = re.search(r"var msg_link\s*=\s*[\"']([^\"']+)", text)
        current_link = html.unescape(msg_link.group(1)).replace("\\x26", "&") if msg_link else ""
        if canonical_url:
            result["url"] = canonical_url
            result["link_type"] = "public_short"
        elif current_link.startswith("http"):
            result["url"] = current_link
            result["link_type"] = "client_signed"
        else:
            result["url"] = f"https://mp.weixin.qq.com/s?__biz={BIZ}&mid={key[0]}&idx={key[1]}&sn={key[2]}"
            result["link_type"] = "client_signed"

        title_match = re.search(r'id=["\']activity-name["\'][^>]*>(.*?)</', text, re.I | re.S)
        if title_match:
            result["title"] = strip_tags(title_match.group(1))
        date_match = re.search(r"create_time\s*:\s*['\"](\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)", text)
        if date_match:
            result["published_at"] = date_match.group(1)
        else:
            timestamp = re.search(r"(?:ori_create_time|create_timestamp)\s*[:=]\s*['\"]?(\d{10})", text)
            if timestamp:
                result["published_at"] = datetime.fromtimestamp(
                    int(timestamp.group(1)), tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M")
        result["status"] = "completed" if result["published_at"] else "partial"
    except Exception as exc:  # keep failed records visible for retry
        result["error"] = str(exc)
    return result


def main() -> int:
    share_files = find_share_data()
    if not share_files:
        print("没有找到包含工映青春文章的微信缓存 Share Data。请先在微信客户端打开该公众号的历史消息/文章。", file=sys.stderr)
        return 2
    signed: dict[tuple[str, str, str], tuple[str, str]] = {}
    for path in share_files:
        signed.update(extract_signed_urls(path))
        for album_url in extract_album_urls(path):
            try:
                for key, value in album_articles(album_url):
                    signed.setdefault(key, value)
            except Exception as exc:
                print(f"合集读取失败：{exc}", file=sys.stderr)
    print(f"从微信缓存发现 {len(signed)} 个工映青春文章地址，正在读取发布时间…")

    records = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_article, item) for item in signed.items()]
        for index, future in enumerate(as_completed(futures), 1):
            records.append(future.result())
            if index % 10 == 0 or index == len(futures):
                print(f"已处理 {index}/{len(futures)}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=365)
    recent = []
    for record in records:
        try:
            date = datetime.fromisoformat(record["published_at"].replace(" ", "T"))
            date = date.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if date >= cutoff and record["url"]:
            record["date_obj"] = date
            recent.append(record)
    recent.sort(key=lambda record: (record["date_obj"], record["title"]), reverse=True)

    OUT_DIR.mkdir(exist_ok=True)
    txt_path = OUT_DIR / "工映青春_微信客户端近一年文章链接.txt"
    public_txt_path = OUT_DIR / "工映青春_近一年可直接打开文章链接.txt"
    signed_txt_path = OUT_DIR / "工映青春_微信客户端签名链接.txt"
    csv_path = OUT_DIR / "工映青春_微信客户端近一年文章链接.csv"
    txt_path.write_text("\n".join(record["url"] for record in recent) + ("\n" if recent else ""), encoding="utf-8")
    public = [record["url"] for record in recent if record.get("link_type") == "public_short"]
    signed = [record["url"] for record in recent if record.get("link_type") == "client_signed"]
    public_txt_path.write_text("\n".join(public) + ("\n" if public else ""), encoding="utf-8")
    signed_txt_path.write_text("\n".join(signed) + ("\n" if signed else ""), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["序号", "标题", "发布时间", "文章链接", "链接类型", "抓取状态"])
        for index, record in enumerate(recent, 1):
            writer.writerow([index, record["title"], record["published_at"], record["url"], record.get("link_type", ""), record["status"]])
    print(f"完成：近一年 {len(recent)} 篇；公开短链接 {len(public)} 条；微信客户端签名链接 {len(signed)} 条")
    print(txt_path)
    print(public_txt_path)
    print(signed_txt_path)
    print(csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
