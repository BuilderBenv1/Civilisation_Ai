"""Agent Town Service Helper — manages the scheduler as a persistent background process.

This module provides programmatic helpers for starting/stopping/checking the
scheduler process on Windows. For day-to-day use, prefer the batch files:

    start_agents.bat      - Launch scheduler in background (survives terminal close)
    stop_agents.bat       - Kill the scheduler process
    status.bat            - Check if running + show recent logs
    install_service.bat   - Register as a Windows Task Scheduler job (auto-start on logon)
    install_service.ps1   - PowerShell alternative for the above

No third-party dependencies. Uses only Windows built-ins and Python stdlib.
"""

import os
import sys
import subprocess
import signal

# Resolve paths relative to this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEDULER_SCRIPT = os.path.join(BASE_DIR, "scheduler.py")
PID_FILE = os.path.join(BASE_DIR, "logs", "scheduler.pid")
ERROR_LOG = os.path.join(BASE_DIR, "logs", "service_error.log")
SCHEDULER_LOG = os.path.join(BASE_DIR, "logs", "scheduler.log")


def _find_pythonw() -> str:
    """Locate pythonw.exe alongside the current Python interpreter."""
    python_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(python_dir, "pythonw.exe")
    if os.path.isfile(pythonw):
        return pythonw
    # Fallback: try PATH
    return "pythonw"


def start():
    """Start the scheduler as a background process using pythonw."""
    if is_running():
        print("Scheduler is already running (PID in %s)" % PID_FILE)
        return

    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)

    pythonw = _find_pythonw()
    err_log = open(ERROR_LOG, "a")

    proc = subprocess.Popen(
        [pythonw, SCHEDULER_SCRIPT],
        cwd=BASE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=err_log,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
    )

    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))

    print("Scheduler started (PID %d)" % proc.pid)
    print("PID file: %s" % PID_FILE)
    print("Error log: %s" % ERROR_LOG)


def stop():
    """Stop the scheduler by reading the PID file and terminating the process."""
    if not os.path.isfile(PID_FILE):
        print("No PID file found. Scheduler may not be running.")
        return

    with open(PID_FILE) as f:
        pid = int(f.read().strip())

    try:
        os.kill(pid, signal.SIGTERM)
        print("Sent SIGTERM to PID %d" % pid)
    except ProcessLookupError:
        print("Process %d not found (already stopped?)" % pid)
    except PermissionError:
        print("Permission denied killing PID %d. Try running as admin." % pid)
    finally:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


def is_running() -> bool:
    """Check whether the scheduler process is still alive."""
    if not os.path.isfile(PID_FILE):
        return False
    with open(PID_FILE) as f:
        try:
            pid = int(f.read().strip())
        except ValueError:
            return False
    try:
        # On Windows os.kill with signal 0 checks existence
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def status():
    """Print current scheduler status and recent log lines."""
    if is_running():
        with open(PID_FILE) as f:
            pid = f.read().strip()
        print("Scheduler is RUNNING (PID %s)" % pid)
    else:
        print("Scheduler is NOT running")

    print()

    # Show last 20 lines of scheduler log
    if os.path.isfile(SCHEDULER_LOG):
        print("=== Last 20 lines of scheduler.log ===")
        with open(SCHEDULER_LOG, "r", errors="replace") as f:
            lines = f.readlines()
            for line in lines[-20:]:
                print(line, end="")
    else:
        print("(No scheduler.log found)")

    # Show last 10 lines of error log if it has content
    if os.path.isfile(ERROR_LOG) and os.path.getsize(ERROR_LOG) > 0:
        print()
        print("=== Last 10 lines of service_error.log ===")
        with open(ERROR_LOG, "r", errors="replace") as f:
            lines = f.readlines()
            for line in lines[-10:]:
                print(line, end="")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Agent Town service helper")
    parser.add_argument("action", choices=["start", "stop", "status"],
                        help="start | stop | status")
    args = parser.parse_args()

    if args.action == "start":
        start()
    elif args.action == "stop":
        stop()
    elif args.action == "status":
        status()
