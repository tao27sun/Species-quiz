@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>nul
if errorlevel 1 goto python
py -3 -m venv .venv
goto check
:python
python -m venv .venv
:check
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo 安装完成。请双击 start.bat 开始考试。
pause
exit /b 0
:failed
echo 安装失败。请确认已安装 Python 3，并检查上方错误信息及网络连接。
pause
exit /b 1
