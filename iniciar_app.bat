@echo off
REM Levanta el servidor local (Flask) y abre la app en el navegador.
REM Dejá esta ventana abierta mientras usás la app. Cerrala (o Ctrl+C) para apagar.

cd /d "%~dp0src"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py app.py
) else (
    python app.py
)

pause
