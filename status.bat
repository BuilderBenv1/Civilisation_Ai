@echo off
REM ============================================================
REM  Agent Town — Check scheduler status and show recent logs
REM ============================================================

cd /d "%~dp0"

echo ============================================================
echo  Agent Town — Status
echo ============================================================
echo.

REM Check via PID file
set RUNNING=0
if exist "logs\scheduler.pid" (
    for /f %%P in (logs\scheduler.pid) do (
        tasklist /fi "PID eq %%P" 2>nul | find "%%P" >nul
        if not errorlevel 1 (
            echo STATUS:  RUNNING ^(PID %%P^)
            set RUNNING=1
        ) else (
            echo STATUS:  NOT RUNNING ^(stale PID file for %%P^)
        )
    )
) else (
    echo STATUS:  NOT RUNNING ^(no PID file^)
)

echo.

REM Check if scheduled task exists
schtasks /query /tn "AgentTown" >nul 2>&1
if not errorlevel 1 (
    echo AUTO-START: Enabled ^(AgentTown scheduled task exists^)
) else (
    echo AUTO-START: Disabled ^(no scheduled task found^)
    echo             Run install_service.bat to enable.
)

echo.

REM Show last 20 lines of scheduler.log
if exist "logs\scheduler.log" (
    echo ============================================================
    echo  Last 20 lines of scheduler.log
    echo ============================================================
    powershell -NoProfile -Command "Get-Content 'logs\scheduler.log' -Tail 20"
) else (
    echo ^(No scheduler.log found^)
)

echo.

REM Show last 10 lines of service_error.log if it has content
if exist "logs\service_error.log" (
    for %%F in ("logs\service_error.log") do (
        if %%~zF gtr 0 (
            echo ============================================================
            echo  Last 10 lines of service_error.log
            echo ============================================================
            powershell -NoProfile -Command "Get-Content 'logs\service_error.log' -Tail 10"
        )
    )
)

echo.
pause
