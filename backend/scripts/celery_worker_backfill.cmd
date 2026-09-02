@echo off
setlocal
set SCRIPT_DIR=%~dp0
pushd "%SCRIPT_DIR%.."
if not exist "storage\logs" mkdir "storage\logs"
set PYTHONPATH=%CD%
echo [%date% %time%] celery backfill worker starting >> "storage\logs\celery-worker-backfill.log"
REM 2026-09-02 - Playwright 解析/截图专用队列，并发 1 避免多 Chromium 打爆机器
".venv\Scripts\python.exe" -m celery -A app.celery_app worker -Q backfill -n backfill@%COMPUTERNAME% -c 1 --pool=solo --loglevel=info >> "storage\logs\celery-worker-backfill.log" 2>&1
echo [%date% %time%] celery backfill worker stopped >> "storage\logs\celery-worker-backfill.log"
popd
endlocal
