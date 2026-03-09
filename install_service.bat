@echo off
REM ============================================================
REM  Agent Town — Install as Windows Scheduled Task (auto-start on logon)
REM ============================================================

cd /d "%~dp0"

echo ============================================================
echo  Agent Town — Service Installer
echo ============================================================
echo.

REM Get the full path to pythonw.exe
for /f "delims=" %%I in ('where pythonw 2^>nul') do set PYTHONW=%%I
if "%PYTHONW%"=="" (
    echo ERROR: pythonw.exe not found on PATH.
    echo Make sure Python is installed and added to PATH.
    pause
    goto :eof
)

set TASK_NAME=AgentTown
set WORK_DIR=%~dp0
REM Remove trailing backslash for cleanliness
set WORK_DIR=%WORK_DIR:~0,-1%
set SCRIPT=%WORK_DIR%\scheduler.py

echo Python (windowless): %PYTHONW%
echo Working directory:   %WORK_DIR%
echo Script:              %SCRIPT%
echo Task name:           %TASK_NAME%
echo.

REM Delete existing task if present
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if not errorlevel 1 (
    echo Removing existing "%TASK_NAME%" task...
    schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
)

REM Create the scheduled task to run at logon
schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%PYTHONW%\" \"%SCRIPT%\"" ^
    /sc onlogon ^
    /rl highest ^
    /f

if errorlevel 1 (
    echo.
    echo FAILED to create scheduled task.
    echo Try running this script as Administrator.
    pause
    goto :eof
)

echo.
echo ============================================================
echo  SUCCESS: "%TASK_NAME%" scheduled task created.
echo  The scheduler will auto-start every time you log in.
echo ============================================================
echo.
echo To start it now:   start_agents.bat
echo To stop it:        stop_agents.bat
echo To check status:   status.bat
echo To uninstall:      schtasks /delete /tn "%TASK_NAME%" /f
echo.
pause
