"""Run the local site and open it after the server is ready."""

from __future__ import annotations

import time
import urllib.request
import webbrowser
from threading import Thread

import uvicorn


def open_browser_when_ready() -> None:
    for _ in range(40):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/status", timeout=1):
                webbrowser.open("http://127.0.0.1:8000")
                return
        except Exception:
            time.sleep(0.5)


def open_existing_server() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/status", timeout=1):
            print("推送助手已经在运行，正在打开网页…")
            webbrowser.open("http://127.0.0.1:8000")
            return True
    except Exception:
        return False


if __name__ == "__main__":
    if open_existing_server():
        raise SystemExit(0)
    Thread(target=open_browser_when_ready, daemon=True).start()
    # This app only uses ordinary HTTP requests. Explicitly disable Uvicorn's
    # optional WebSocket auto-detection, which can conflict with other packages
    # installed in the shared Python environment.
    uvicorn.run("app:app", host="127.0.0.1", port=8000, log_level="info", ws="none")
