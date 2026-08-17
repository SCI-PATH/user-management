@echo off
cd /d %~dp0
if not exist .venv (
  echo Create venv first: py -3.12 -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
  exit /b 1
)
if not exist .env copy .env.example .env
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
