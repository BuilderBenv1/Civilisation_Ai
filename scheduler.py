"""Agent Town Scheduler — runs the civilisation, self-healing on crash.

Scout: every 2 hours
Worker: continuous loop (polls every 60s)
BD: every 2 hours
Darwin: after every Scout cycle + independent 6h loop
Weekly report: Monday 8am UK time

Each agent runs in its own thread. If one crashes, the scheduler restarts it
after a backoff delay. The civilisation endures.
"""

import sys
import os
import time
import threading
import traceback
import signal
import schedule
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.config import (
    get_logger, SCOUT_INTERVAL_SECONDS, BD_INTERVAL_SECONDS, WORKER_POLL_SECONDS,
)
from shared.telegram import send as tg_send, notify_error

log = get_logger("scheduler")

# Tracks running agent threads
_agents: dict[str, threading.Thread] = {}
_shutdown = threading.Event()

# Backoff state per agent
_restart_counts: dict[str, int] = {}
MAX_RESTART_BACKOFF = 300  # 5 minutes max


DARWIN_INTERVAL_SECONDS = int(os.getenv("DARWIN_INTERVAL_SECONDS", "21600"))  # 6 hours


def _run_agent_loop(agent_name: str, run_fn, interval_seconds: int):
    """Generic agent loop with crash recovery. Used for Scout, BD, Darwin."""
    while not _shutdown.is_set():
        try:
            log.info("[%s] Running cycle", agent_name)
            run_fn()
            _restart_counts[agent_name] = 0  # Reset on success
            log.info("[%s] Cycle complete, sleeping %ds", agent_name, interval_seconds)
        except Exception as e:
            log.error("[%s] Cycle crashed: %s\n%s", agent_name, e, traceback.format_exc())
        _shutdown.wait(interval_seconds)


def _run_scout_then_darwin():
    """Scout cycle followed by Darwin. Darwin evolves based on what Scout found."""
    from agents.scout.scout import run_cycle as scout_cycle
    from agents.darwin.darwin import run_cycle as darwin_cycle

    while not _shutdown.is_set():
        try:
            log.info("[scout] Running cycle")
            scout_cycle()
            _restart_counts["scout"] = 0
            log.info("[scout] Cycle complete — triggering Darwin")

            # Darwin runs immediately after Scout
            try:
                log.info("[darwin] Running post-Scout cycle")
                darwin_cycle()
                _restart_counts["darwin"] = 0
                log.info("[darwin] Post-Scout cycle complete")
            except Exception as e:
                log.error("[darwin] Post-Scout cycle crashed: %s\n%s", e, traceback.format_exc())

        except Exception as e:
            log.error("[scout] Cycle crashed: %s\n%s", e, traceback.format_exc())

        _shutdown.wait(SCOUT_INTERVAL_SECONDS)


def _run_worker_loop():
    """Worker runs its own continuous loop."""
    from agents.worker.worker import run_cycle
    while not _shutdown.is_set():
        try:
            run_cycle()
            _restart_counts["worker"] = 0
        except Exception as e:
            log.error("[worker] Cycle crashed: %s\n%s", e, traceback.format_exc())
        _shutdown.wait(WORKER_POLL_SECONDS)


def _start_agent(name: str, target_fn, *args):
    """Start an agent thread. If it's already running, skip."""
    if name in _agents and _agents[name].is_alive():
        return

    count = _restart_counts.get(name, 0)
    if count > 0:
        backoff = min(2 ** count, MAX_RESTART_BACKOFF)
        log.warning("[%s] Restart #%d, backing off %ds", name, count, backoff)
        time.sleep(backoff)

    _restart_counts[name] = count + 1

    thread = threading.Thread(target=target_fn, args=args, name=f"agent-{name}", daemon=True)
    thread.start()
    _agents[name] = thread
    log.info("[%s] Agent thread started", name)


def _health_check():
    """Check all agent threads and restart any that died."""
    for name in list(_agents.keys()):
        if not _agents[name].is_alive():
            log.warning("[%s] Agent thread died, restarting", name)
            notify_error(name, f"Agent thread died — auto-restarting (attempt #{_restart_counts.get(name, 0) + 1})")
            if name == "scout":
                _start_agent("scout", _run_scout_then_darwin)
            elif name == "worker":
                _start_agent("worker", _run_worker_loop)
            elif name == "bd":
                from agents.bd.bd import run_cycle as bd_cycle
                _start_agent("bd", _run_agent_loop, "bd", bd_cycle, BD_INTERVAL_SECONDS)
            elif name == "darwin":
                from agents.darwin.darwin import run_cycle as darwin_cycle
                _start_agent("darwin", _run_agent_loop, "darwin", darwin_cycle, DARWIN_INTERVAL_SECONDS)


def _run_weekly_report():
    """Trigger weekly report — runs on schedule."""
    try:
        from report import send_weekly_report
        send_weekly_report()
    except Exception as e:
        log.error("Weekly report failed: %s", e)


def main():
    log.info("=" * 60)
    log.info("AGENT TOWN SCHEDULER STARTING")
    log.info("=" * 60)
    log.info("Scout interval: %ds", SCOUT_INTERVAL_SECONDS)
    log.info("BD interval: %ds", BD_INTERVAL_SECONDS)
    log.info("Worker poll: %ds", WORKER_POLL_SECONDS)

    # Handle graceful shutdown
    def shutdown_handler(signum, frame):
        log.info("Shutdown signal received, stopping agents...")
        _shutdown.set()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Import agent run functions
    from agents.bd.bd import run_cycle as bd_cycle
    from agents.darwin.darwin import run_cycle as darwin_cycle

    # Start all agents — Scout+Darwin run as a pair, Darwin also runs independently
    _start_agent("scout", _run_scout_then_darwin)
    _start_agent("worker", _run_worker_loop)
    _start_agent("bd", _run_agent_loop, "bd", bd_cycle, BD_INTERVAL_SECONDS)
    _start_agent("darwin", _run_agent_loop, "darwin", darwin_cycle, DARWIN_INTERVAL_SECONDS)

    # Schedule weekly report for Monday 8am UK
    schedule.every().monday.at("08:00").do(_run_weekly_report)
    log.info("Weekly report scheduled for Monday 08:00 UK")

    # Main loop: health check + schedule
    log.info("All agents launched. Entering main loop.")
    tg_send("<b>Agent Town Online</b>\nScout, Worker, BD, Darwin all launched.\nThe civilisation endures.")
    while not _shutdown.is_set():
        _health_check()
        schedule.run_pending()
        _shutdown.wait(30)  # Health check every 30s

    log.info("Scheduler shutting down")
    # Wait for threads to finish
    for name, thread in _agents.items():
        log.info("Waiting for %s to finish...", name)
        thread.join(timeout=10)
    log.info("Shutdown complete")


if __name__ == "__main__":
    main()
