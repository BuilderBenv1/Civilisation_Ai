@echo off
REM ============================================================
REM  Agent Town — Stop the scheduler process
REM ============================================================

cd /d "%~dp0"

REM Try PID file first
if exist "logs\scheduler.pid" (
    for /f %%P in (logs\scheduler.pid) do (
        echo Stopping scheduler process ^(PID %%P^)...
        taskkill /PID %%P /F >nul 2>&1
        if not errorlevel 1 (
            echo Scheduler stopped.
        ) else (
            echo Process %%P was not running.
        )
    )
    del "logs\scheduler.pid" 2>nul
    goto :done
)

REM No PID file — try to find pythonw running scheduler.py
echo No PID file found. Searching for scheduler process...
wmic process where "commandline like '%%scheduler.py%%' and name='pythonw.exe'" get processid 2>nul | findstr /r "[0-9]" >nul
if not errorlevel 1 (
    echo Found scheduler process. Killing...
    wmic process where "commandline like '%%scheduler.py%%' and name='pythonw.exe'" call terminate >nul 2>&1
    echo Scheduler stopped.
    goto :done
)

REM Last resort — kill all pythonw (ask first)
echo Could not find a specific scheduler process.
echo.
set /p CONFIRM="Kill ALL pythonw.exe processes? (y/N): "
if /i "%CONFIRM%"=="y" (
    taskkill /im pythonw.exe /f >nul 2>&1
    echo All pythonw processes killed.
) else (
    echo Aborted.
)

:done
REM Clean up stale PID file
if exist "logs\scheduler.pid" del "logs\scheduler.pid" 2>nul
echo.
echo Done.
