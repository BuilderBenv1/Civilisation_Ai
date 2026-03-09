@echo off
schtasks /create /tn "AgentTown" /tr "C:\Users\theka\AppData\Local\Programs\Python\Python313\pythonw.exe \"C:\Users\theka\OneDrive\Desktop\Agent Town\agent_town\scheduler.py\"" /sc onlogon /f
if %errorlevel% equ 0 (
    echo AgentTown scheduled task created successfully.
    echo It will auto-start every time you log in.
) else (
    echo Failed to create task. Try running as Administrator.
)
pause
