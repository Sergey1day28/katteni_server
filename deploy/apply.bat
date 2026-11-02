@echo off
cd /d "%~dp0.."
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
)
python -m pip install -r requirements-farm.txt
python manage.py migrate
echo Дальше на этой машине: start-test.bat (сайт и часы). Агент: start-agent-hidden.bat.
