@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer, then run this file again.
  cmd /k
  exit /b 1
)

python -c "import requests, bs4, lxml" >nul 2>&1
if errorlevel 1 (
  echo Installing required components. Internet access is needed for the first run.
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Installation failed. Check the network and try again.
    cmd /k
    exit /b 1
  )
)

if "%~1"=="" (
  python -X utf8 -u importer.py import
) else (
  python -X utf8 -u importer.py import "%~1"
)
set "IMPORT_EXIT=%ERRORLEVEL%"
echo.
if "%IMPORT_EXIT%"=="0" (
  echo Import finished. Results are saved in the data folder.
) else (
  echo Import finished with error code %IMPORT_EXIT%.
)
echo This window will stay open. Type exit and press Enter to close it.
cmd /k
