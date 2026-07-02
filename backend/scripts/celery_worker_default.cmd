@echo off
setlocal
set SCRIPT_DIR=%~dp0
pushd "%SCRIPT_DIR%.."
if not exist "storage\logs" mkdir "storage\logs"
set PYTHONPATH=%CD%
echo [%date% %time%] celery default worker starting >> "storage\logs\celery-worker-default.log"
".venv\Scripts\python.exe" -m celery -A app.celery_app worker -Q default -n default@localhost -c 2 --pool=solo --loglevel=info >> "storage\logs\celery-worker-default.log" 2>&1
echo [%date% %time%] celery default worker stopped >> "storage\logs\celery-worker-default.log"
popd
endlocal
