@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
  echo 没找到 Python。请先安装 Python 3.11 或更新版本。
  pause
  exit /b 1
)

python -c "import fastapi, uvicorn, openai, dotenv" >nul 2>&1
if errorlevel 1 (
  echo 正在准备聊天网页所需组件，首次运行需要联网...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo 组件安装失败，请检查网络后重新双击。
    pause
    exit /b 1
  )
)

python -X utf8 launch_chat.py
if errorlevel 1 (
  echo.
  echo 推送助手启动失败。请保留此窗口中的错误信息。
)
pause
