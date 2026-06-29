@echo off
setlocal
set SCRIPT_DIR=%~dp0
pushd "%SCRIPT_DIR%.."
if not exist "storage\logs" mkdir "storage\logs"
echo [%date% %time%] run due scheduled tasks >> "storage\logs\scheduler.log"
".venv\Scripts\python.exe" "%SCRIPT_DIR%run_due_scheduled_tasks.py" --limit 20 --max-prompts 50 >> "storage\logs\scheduler.log" 2>&1
echo. >> "storage\logs\scheduler.log"
popd
endlocal
