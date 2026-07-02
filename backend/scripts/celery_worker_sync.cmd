@echo off
setlocal
set SCRIPT_DIR=%~dp0
pushd "%SCRIPT_DIR%.."
if not exist "storage\logs" mkdir "storage\logs"
set PYTHONPATH=%CD%
echo [%date% %time%] celery sync worker starting >> "storage\logs\celery-worker-sync.log"
".venv\Scripts\python.exe" -m celery -A app.celery_app worker -Q sync -n sync@localhost -c 8 --pool=solo --loglevel=info >> "storage\logs\celery-worker-sync.log" 2>&1
echo [%date% %time%] celery sync worker stopped >> "storage\logs\celery-worker-sync.log"
popd
endlocal
