@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m farm_agent
) else (
    start "" pythonw -m farm_agent
)
