@echo off
rem SPEC-Z005 manual launcher (same as the Pinokio Start button): http://127.0.0.1:42054
cd /d F:\code\codex-render-work\zcode-z5-poc\media-poc
if not exist venv\Scripts\python.exe (
  python -m venv venv
  venv\Scripts\python.exe -m pip install --upgrade pip
  venv\Scripts\python.exe -m pip install -r requirements.txt
  venv\Scripts\python.exe selfcheck.py
)
venv\Scripts\python.exe server.py
