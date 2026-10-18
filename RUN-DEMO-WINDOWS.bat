@echo off
setlocal
cd /d "%~dp0frontend"
echo Starting Socratic local demo at http://localhost:8080
start "Socratic Demo" http://localhost:8080
python -m http.server 8080
if errorlevel 1 (
  echo.
  echo Could not start the server. Make sure Python is installed and try:
  echo   cd frontend
  echo   python -m http.server 8080
  pause
)
endlocal
