@echo off
rem Start Annotshot from the source folder with no console window.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0Annotshot.pyw" %*
