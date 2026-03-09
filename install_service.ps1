#Requires -Version 5.1
<#
.SYNOPSIS
    Agent Town — Install as Windows Scheduled Task (PowerShell version)

.DESCRIPTION
    Creates a scheduled task called "AgentTown" that launches the scheduler
    via pythonw.exe at every user logon. The task runs in the background
    with no visible window.

.NOTES
    Run this script from an elevated (Admin) PowerShell prompt:
        powershell -ExecutionPolicy Bypass -File install_service.ps1
#>

$ErrorActionPreference = "Stop"

# Resolve paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SchedulerScript = Join-Path $ScriptDir "scheduler.py"
$LogDir = Join-Path $ScriptDir "logs"
$TaskName = "AgentTown"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Agent Town — Service Installer (PowerShell)"               -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Ensure logs directory exists
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    Write-Host "Created logs directory: $LogDir"
}

# Find pythonw.exe
$PythonW = Get-Command pythonw.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
if (-not $PythonW) {
    # Try common locations
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\pythonw.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\pythonw.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $PythonW = $c
            break
        }
    }
}

if (-not $PythonW) {
    Write-Host "ERROR: pythonw.exe not found." -ForegroundColor Red
    Write-Host "Make sure Python is installed and added to PATH." -ForegroundColor Red
    exit 1
}

Write-Host "Python windowless: $PythonW"
Write-Host "Working directory:   $ScriptDir"
Write-Host "Script:              $SchedulerScript"
Write-Host "Task name:           $TaskName"
Write-Host ""

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing '$TaskName' task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Build the scheduled task
$Action = New-ScheduledTaskAction `
    -Execute $PythonW `
    -Argument "`"$SchedulerScript`"" `
    -WorkingDirectory $ScriptDir

$Trigger = New-ScheduledTaskTrigger -AtLogOn

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# Register the task for the current user
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Agent Town scheduler — runs Scout, Worker, and BD agents in the background." `
    | Out-Null

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  SUCCESS: '$TaskName' scheduled task created."              -ForegroundColor Green
Write-Host "  The scheduler will auto-start every time you log in."     -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start now:     .\start_agents.bat"
Write-Host "To stop:          .\stop_agents.bat"
Write-Host "To check status:  .\status.bat"
Write-Host "To uninstall:     Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host ""

# Offer to start immediately
$startNow = Read-Host "Start the scheduler now? (Y/n)"
if ($startNow -eq "" -or $startNow -ieq "y" -or $startNow -ieq "yes") {
    Write-Host "Starting scheduler..."
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 2

    $task = Get-ScheduledTask -TaskName $TaskName
    if ($task.State -eq "Running") {
        Write-Host "Scheduler is running." -ForegroundColor Green
    } else {
        Write-Host "Task state: $($task.State)" -ForegroundColor Yellow
        Write-Host "Check logs\service_error.log for details."
    }
}
