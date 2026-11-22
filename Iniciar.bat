@echo off
rem Abre o aplicativo. Tambem da para arrastar videos em cima deste arquivo.
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0app.py" %*
) else (
    python "%~dp0app.py" %*
    if errorlevel 1 pause
)
