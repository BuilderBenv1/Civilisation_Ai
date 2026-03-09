@echo off
REM Install Agent Town to Windows Startup folder — no admin required
REM Creates a shortcut that runs pythonw scheduler.py on login

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "PYTHONW=C:\Users\theka\AppData\Local\Programs\Python\Python313\pythonw.exe"
set "SCRIPT=C:\Users\theka\OneDrive\Desktop\Agent Town\agent_town\scheduler.py"
set "WORKDIR=C:\Users\theka\OneDrive\Desktop\Agent Town\agent_town"

REM Create a VBS script to make a shortcut (Windows has no native shortcut creation from cmd)
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%TEMP%\make_shortcut.vbs"
echo Set oLink = oWS.CreateShortcut("%STARTUP%\AgentTown.lnk") >> "%TEMP%\make_shortcut.vbs"
echo oLink.TargetPath = "%PYTHONW%" >> "%TEMP%\make_shortcut.vbs"
echo oLink.Arguments = """%SCRIPT%""" >> "%TEMP%\make_shortcut.vbs"
echo oLink.WorkingDirectory = "%WORKDIR%" >> "%TEMP%\make_shortcut.vbs"
echo oLink.Description = "Agent Town Scheduler" >> "%TEMP%\make_shortcut.vbs"
echo oLink.Save >> "%TEMP%\make_shortcut.vbs"

cscript //nologo "%TEMP%\make_shortcut.vbs"
del "%TEMP%\make_shortcut.vbs"

if exist "%STARTUP%\AgentTown.lnk" (
    echo SUCCESS: Agent Town added to Windows Startup
    echo Location: %STARTUP%\AgentTown.lnk
    echo It will auto-start every time you log in.
) else (
    echo FAILED to create startup shortcut.
)
