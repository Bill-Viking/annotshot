@echo off
rem Start Annotshot from the source folder with no console window.
cd /d "%~dp0"
start "" "%~dp0.venv\Scripts\pythonw.exe" -m annotshot
