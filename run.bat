@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtualenv...
  python -m venv .venv
  if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" -c "import customtkinter, pretty_midi, sounddevice, fpdf2, soxr" 2>nul
if errorlevel 1 (
  echo Installing dependencies...
  ".venv\Scripts\python.exe" -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
  if errorlevel 1 exit /b 1
)

if not exist "docs\manual.pdf" (
  echo Building manual PDF...
  ".venv\Scripts\python.exe" scripts\build_manual_pdf.py
)

".venv\Scripts\python.exe" main.py
endlocal
