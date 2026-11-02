@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
)
call "%~dp0start-clock-hidden.bat"
python manage.py runserver 127.0.0.1:8000
