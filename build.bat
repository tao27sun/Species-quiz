@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" -m pip install "pyinstaller>=6,<7"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --console --name PlantQuiz --add-data "templates;templates" --add-data "static;static" --distpath "release\PlantQuiz" --workpath "build" --specpath "." "app.py"
if errorlevel 1 goto failed
copy /y "plants.xlsx" "release\PlantQuiz\plants.xlsx" >nul
if errorlevel 1 goto failed
copy /y "PORTABLE_README.txt" "release\PlantQuiz\README.txt" >nul
if errorlevel 1 goto failed
powershell -NoProfile -Command "Compress-Archive -Path 'release\PlantQuiz' -DestinationPath 'release\PlantQuiz-Windows-x64.zip' -Force"
if errorlevel 1 goto failed
echo 打包完成：release\PlantQuiz-Windows-x64.zip
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
