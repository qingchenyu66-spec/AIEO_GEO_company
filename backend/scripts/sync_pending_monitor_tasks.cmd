@echo off
setlocal
set SCRIPT_DIR=%~dp0
pushd "%SCRIPT_DIR%.."
if not exist "storage\logs" mkdir "storage\logs"
echo [%date% %time%] sync pending monitor tasks >> "storage\logs\sync.log"
".venv\Scripts\python.exe" "%SCRIPT_DIR%sync_pending_monitor_tasks.py" --limit 50 >> "storage\logs\sync.log" 2>&1
echo. >> "storage\logs\sync.log"
popd
endlocal
