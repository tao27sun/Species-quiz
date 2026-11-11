@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" -m pip install "pyinstaller>=6,<7"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --console --name SpeciesQuiz --add-data "templates;templates" --add-data "static;static" --distpath "release\SpeciesQuiz" --workpath "build" --specpath "." "app.py"
if errorlevel 1 goto failed
copy /y "species.xlsx" "release\SpeciesQuiz\species.xlsx" >nul
if errorlevel 1 goto failed
copy /y "PORTABLE_README.txt" "release\SpeciesQuiz\README.txt" >nul
if errorlevel 1 goto failed
powershell -NoProfile -Command "Compress-Archive -Path 'release\SpeciesQuiz' -DestinationPath 'release\SpeciesQuiz-Windows-x64.zip' -Force"
if errorlevel 1 goto failed
echo 打包完成：release\SpeciesQuiz-Windows-x64.zip
pause
exit /b 0
:missing
echo 请先双击 install.bat 安装构建环境。
pause
exit /b 1
:failed
echo 打包失败，请检查上方错误信息。
pause
exit /b 1
