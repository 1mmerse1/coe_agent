@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set "COE_PYTHON=python"
if exist "D:\python\python.exe" set "COE_PYTHON=D:\python\python.exe"
if exist "%~dp0.venv\Scripts\python.exe" set "COE_PYTHON=%~dp0.venv\Scripts\python.exe"

"%COE_PYTHON%" --version >nul 2>&1
if errorlevel 1 (
  echo 没找到 Python。请先安装 Python 3.11 或更新版本。
  pause
  exit /b 1
)

"%COE_PYTHON%" -c "import fastapi, uvicorn, openai, dotenv, pypdf, pypdfium2, PIL, docx, openpyxl, reportlab" >nul 2>&1
if errorlevel 1 (
  echo 正在准备聊天网页所需组件，首次运行需要联网...
  "%COE_PYTHON%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo 组件安装失败，请检查网络后重新双击。
    pause
    exit /b 1
  )
)

"%COE_PYTHON%" -X utf8 "src\launch_chat.py"
if errorlevel 1 (
  echo.
  echo 推送助手启动失败。请保留此窗口中的错误信息。
)
pause
