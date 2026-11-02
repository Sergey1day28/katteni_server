@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" /D "%~dp0" ".venv\Scripts\pythonw.exe" -m farm_clock
) else (
    start "" /D "%~dp0" pythonw -m farm_clock
)
