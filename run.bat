@echo off
cd /d "%~dp0backend"
call ..\venv\Scripts\activate.bat
python manage.py runserver
