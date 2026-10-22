@echo off
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%backend\.venv\Scripts\python.exe" (
  echo Backend environment missing. See README.md to create backend\.venv and install requirements.
  exit /b 1
)
if not exist "%ROOT%frontend\node_modules\vite\bin\vite.js" (
  echo Frontend dependencies missing. Run npm install in the frontend folder first.
  exit /b 1
)
start "NutriSnap API" /D "%ROOT%backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
start "NutriSnap Web" /D "%ROOT%frontend" cmd /k "npm run dev"
echo NutriSnap is starting. Open http://localhost:5173
