@echo off
rem Reachy HW4 Motion Lab - first-time setup on Windows (needs internet once).
rem Creates .venv in this folder with the exact versions of constraints.txt (reachy-mini 1.11.0, no upgrades).
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 goto :nouv
if not exist .venv\Scripts\python.exe uv venv --python 3.12 .venv
if errorlevel 1 goto :fail
uv pip install --python .venv\Scripts\python.exe -c constraints.txt -e ".[sim,analysis,gui]" av
if errorlevel 1 goto :fail
.venv\Scripts\python -m reachy_motion env
if errorlevel 1 goto :fail
echo.
echo [setup] Done. The last line above must say "pins OK". Start the GUI with run_gui.bat
pause
exit /b 0
:nouv
echo [setup] uv is not installed. Install it with this one line in PowerShell:
echo     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
echo Then open a NEW terminal window and run setup_windows.bat again.
pause
exit /b 1
:fail
echo [setup] FAILED - read the messages above.
pause
exit /b 1
