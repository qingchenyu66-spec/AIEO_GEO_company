@echo off
setlocal
set SCRIPT_DIR=%~dp0
pushd "%SCRIPT_DIR%.."
if not exist "storage\logs" mkdir "storage\logs"
set PYTHONPATH=%CD%
echo [%date% %time%] flower starting >> "storage\logs\celery-flower.log"
".venv\Scripts\python.exe" "%SCRIPT_DIR%start_flower.py" >> "storage\logs\celery-flower.log" 2>&1
echo [%date% %time%] flower stopped >> "storage\logs\celery-flower.log"
popd
endlocal
