@echo off
cd /d C:\Projects\PiperScenarioLab
if exist C:\Projects\Piper\.venv\Scripts\python.exe (
  C:\Projects\Piper\.venv\Scripts\python.exe launcher.py
) else (
  python launcher.py
)
if errorlevel 1 pause
