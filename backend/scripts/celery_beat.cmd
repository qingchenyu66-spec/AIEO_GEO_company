@echo off
setlocal
set SCRIPT_DIR=%~dp0
pushd "%SCRIPT_DIR%.."
if not exist "storage\logs" mkdir "storage\logs"
set PYTHONPATH=%CD%
echo [%date% %time%] celery beat starting >> "storage\logs\celery-beat.log"
".venv\Scripts\python.exe" -m celery -A app.celery_app beat --loglevel=info >> "storage\logs\celery-beat.log" 2>&1
echo [%date% %time%] celery beat stopped >> "storage\logs\celery-beat.log"
popd
endlocal
