"""Run the local site and open it after the server is ready."""

from __future__ import annotations

import time
import urllib.request
import webbrowser
import os
import socket
from pathlib import Path
from threading import Thread

from dotenv import load_dotenv
import uvicorn


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
HOST = os.getenv("APP_HOST", "127.0.0.1").strip() or "127.0.0.1"
PORT = int(os.getenv("APP_PORT", "8000"))


def open_browser_when_ready() -> None:
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status", timeout=1):
                webbrowser.open(f"http://127.0.0.1:{PORT}")
                return
        except Exception:
            time.sleep(0.5)


def open_existing_server() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status", timeout=1):
            print("推送助手已经在运行，正在打开网页…")
            webbrowser.open(f"http://127.0.0.1:{PORT}")
            return True
    except Exception:
        return False


if __name__ == "__main__":
    if HOST not in {"127.0.0.1", "localhost"} and not os.getenv("APP_ACCESS_CODE", "").strip():
        print("提示：当前绑定了局域网地址，但没有设置 APP_ACCESS_CODE。建议在 .env 中设置共享访问码。")
    if open_existing_server():
        raise SystemExit(0)
    Thread(target=open_browser_when_ready, daemon=True).start()
    # This app only uses ordinary HTTP requests. Explicitly disable Uvicorn's
    # optional WebSocket auto-detection, which can conflict with other packages
    # installed in the shared Python environment.
    print(f"本机访问：http://127.0.0.1:{PORT}")
    if HOST not in {"127.0.0.1", "localhost"}:
        try:
            lan_ip = socket.gethostbyname(socket.gethostname())
            print(f"局域网访问：http://{lan_ip}:{PORT}")
        except OSError:
            print(f"局域网访问：http://你的电脑IP:{PORT}")
        print("访问码已启用" if os.getenv("APP_ACCESS_CODE", "").strip() else "访问码未启用")
    uvicorn.run("app:app", host=HOST, port=PORT, log_level="info", ws="none")
