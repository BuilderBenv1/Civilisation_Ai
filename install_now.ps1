$ErrorActionPreference = "Stop"
$ScriptDir = "C:\Users\theka\OneDrive\Desktop\Agent Town\agent_town"
$SchedulerScript = Join-Path $ScriptDir "scheduler.py"
$TaskName = "AgentTown"

$PythonW = Get-Command pythonw.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
if (-not $PythonW) {
    $PythonW = "C:\Users\theka\AppData\Local\Programs\Python\Python313\pythonw.exe"
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task"
}

$Action = New-ScheduledTaskAction -Execute $PythonW -Argument """$SchedulerScript""" -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Agent Town scheduler" | Out-Null

Write-Host "AgentTown scheduled task created successfully"
$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "Task: $($task.TaskName) - State: $($task.State)"
