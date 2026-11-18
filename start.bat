@echo off
REM Narx kuzatuvchi: serverni ishga tushiradi va brauzerda saytni ochadi.
cd /d "%~dp0"
start "" http://127.0.0.1:8000/
.venv\Scripts\python manage.py runserver
pause
