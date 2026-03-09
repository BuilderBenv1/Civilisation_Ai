@echo off
REM ============================================================
REM  Agent Town — Start scheduler in background (survives terminal close)
REM ============================================================

REM Change to the directory where this batch file lives
cd /d "%~dp0"

REM Create logs directory if it doesn't exist
if not exist "logs" mkdir "logs"

REM Check if already running via PID file
if exist "logs\scheduler.pid" (
    for /f %%P in (logs\scheduler.pid) do (
        tasklist /fi "PID eq %%P" 2>nul | find "%%P" >nul
        if not errorlevel 1 (
            echo Scheduler is already running ^(PID %%P^)
            goto :eof
        )
    )
    REM PID file exists but process is dead — clean up
    del "logs\scheduler.pid"
)

REM Find pythonw.exe
where pythonw >nul 2>&1
if errorlevel 1 (
    echo ERROR: pythonw.exe not found on PATH
    echo Make sure Python is installed and added to PATH
    pause
    goto :eof
)

REM Launch scheduler windowless, redirect stderr to error log
echo Starting Agent Town scheduler...
start "" /B pythonw scheduler.py 2>>"logs\service_error.log"

REM Give it a moment to start, then grab the PID
timeout /t 2 /nobreak >nul

REM Find the pythonw process running scheduler.py
for /f "tokens=2" %%P in ('wmic process where "commandline like '%%scheduler.py%%' and name='pythonw.exe'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    echo %%P>"logs\scheduler.pid"
    echo Scheduler started ^(PID %%P^)
    goto :started
)

REM Fallback: try to get PID via tasklist
for /f "tokens=2" %%P in ('tasklist /fi "imagename eq pythonw.exe" /fo list 2^>nul ^| findstr /i "PID"') do (
    echo %%P>"logs\scheduler.pid"
    echo Scheduler started ^(PID %%P^)
    goto :started
)

echo Scheduler launched but could not capture PID.
echo Check logs\service_error.log if it didn't start properly.

:started
echo.
echo Logs:     logs\scheduler.log
echo Errors:   logs\service_error.log
echo PID file: logs\scheduler.pid
echo.
echo The scheduler will keep running after you close this terminal.
echo Use stop_agents.bat to stop it.
