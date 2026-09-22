@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto failed
exit /b 0
:missing
echo 请先双击 install.bat 安装运行环境。
pause
exit /b 1
:failed
echo 程序启动失败，请检查上方错误信息。
pause
exit /b 1
