@echo off
rem Start Video Studio without Pinokio:  start-video-studio.bat          (normal)
rem                                      start-video-studio.bat reload   (restart automatically when code changes - stops a running render)
rem Then open http://127.0.0.1:42020   (WanGP and Ollama still have to be running for narration, stills and clip checks)
setlocal
cd /d F:\code\video-studio\app
rem Pinokio's bundled Node.js / ffmpeg live in its conda folder; add them so Remotion (npx) works outside Pinokio
set "PATH=C:\pinokio\bin\miniconda;C:\pinokio\bin\miniconda\Scripts;C:\pinokio\bin\miniconda\Library\bin;%PATH%"
call env\Scripts\activate.bat
set PORT=42020
set PYTHONUNBUFFERED=1
if /i "%~1"=="reload" (set VS_RELOAD=1) else (set VS_RELOAD=)
where npx >nul 2>nul || echo WARNING: Node.js (npx) not found on PATH - Shorts can't render. Start Video Studio from Pinokio, or install Node.js.
start "" http://127.0.0.1:42020
python server.py
endlocal
