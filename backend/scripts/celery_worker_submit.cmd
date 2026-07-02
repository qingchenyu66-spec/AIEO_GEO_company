@echo off
setlocal
set SCRIPT_DIR=%~dp0
pushd "%SCRIPT_DIR%.."
if not exist "storage\logs" mkdir "storage\logs"
set PYTHONPATH=%CD%
echo [%date% %time%] celery submit worker starting >> "storage\logs\celery-worker-submit.log"
".venv\Scripts\python.exe" -m celery -A app.celery_app worker -Q submit -n submit@localhost -c 4 --pool=solo --loglevel=info >> "storage\logs\celery-worker-submit.log" 2>&1
echo [%date% %time%] celery submit worker stopped >> "storage\logs\celery-worker-submit.log"
popd
endlocal
