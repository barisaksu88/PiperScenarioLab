@echo off
cd /d C:\Projects\PiperScenarioLab
set SCENARIO_LLM_MODE=piper
set SCENARIO_LLM_BASE_URL=http://127.0.0.1:8081
set SCENARIO_LLM_MODEL=qwen
set SCENARIO_REBUILD_FRONTEND_ON_BOOT=1
if exist C:\Projects\Piper\.venv\Scripts\python.exe (
  C:\Projects\Piper\.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8080 --reload
) else (
  python -m uvicorn app:app --host 0.0.0.0 --port 8080 --reload
)
if errorlevel 1 pause
