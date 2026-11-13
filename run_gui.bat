@echo off
rem Reachy HW4 Motion Lab (GUI). Results are written in this folder: results\lab
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto :nosetup
.venv\Scripts\python -m reachy_motion gui
if errorlevel 1 pause
exit /b 0
:nosetup
echo [run] .venv not found - run setup_windows.bat first.
pause
exit /b 1
