"""Spawner — manages Worker clone lifecycle.

When Worker's queue exceeds capacity, Darwin spawns clones.
When the queue drains, Darwin kills them.
Max 5 Workers. Each inherits the Prime Directive.
"""

import sys
import os
import subprocess
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.config import get_logger, WORKER_POLL_SECONDS
from shared.supabase_client import get_client

log = get_logger("darwin.spawner")

MAX_WORKERS = 5

# Track active worker clones: {clone_id: {"process": Popen, "thread": Thread}}
_clones: dict[str, dict] = {}


def get_queue_depth() -> int:
    """Count opportunities waiting for Worker (new status)."""
    try:
        sb = get_client()
        result = sb.table("opportunities").select("id", count="exact").eq("status", "new").execute()
        return result.count or 0
    except Exception as e:
        log.error("Failed to check queue depth: %s", e)
        return 0


def get_active_clone_count() -> int:
    """Count running clone processes."""
    alive = {k: v for k, v in _clones.items() if v["process"].poll() is None}
    _clones.clear()
    _clones.update(alive)
    return len(_clones)


def spawn_clone() -> str | None:
    """Spawn a new Worker clone as a subprocess. Returns clone ID or None."""
    active = get_active_clone_count()
    if active + 1 >= MAX_WORKERS:  # +1 for the primary Worker
        log.warning("At max workers (%d), cannot spawn more", MAX_WORKERS)
        return None

    clone_id = f"worker-{active + 2}"  # worker-2, worker-3, etc.
    log.info("Spawning clone: %s", clone_id)

    # Register clone in Supabase
    try:
        sb = get_client()
        # Find primary worker's agent ID as parent
        parent = sb.table("agents").select("id").eq("name", "Worker").limit(1).execute()
        parent_id = parent.data[0]["id"] if parent.data else None

        sb.table("agents").insert({
            "name": clone_id,
            "agent_type": "worker",
            "parent_agent": parent_id,
            "generation": 1,
            "status": "active",
        }).execute()
    except Exception as e:
        log.error("Failed to register clone %s: %s", clone_id, e)

    # Spawn as subprocess — runs worker.py with --once in a loop
    worker_script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "worker", "worker.py",
    )
    python = sys.executable or "python"

    proc = subprocess.Popen(
        [python, worker_script, "--once"],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    _clones[clone_id] = {"process": proc}
    log.info("Clone %s spawned (PID %d)", clone_id, proc.pid)
    return clone_id


def terminate_clone(clone_id: str):
    """Kill a specific clone."""
    if clone_id not in _clones:
        return

    proc = _clones[clone_id]["process"]
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    log.info("Clone %s terminated", clone_id)

    # Mark terminated in Supabase
    try:
        sb = get_client()
        sb.table("agents").update({
            "status": "terminated",
            "terminated_at": "now()",
        }).eq("name", clone_id).execute()
    except Exception as e:
        log.error("Failed to mark clone %s terminated: %s", clone_id, e)

    del _clones[clone_id]


def terminate_all():
    """Kill all clones."""
    for clone_id in list(_clones.keys()):
        terminate_clone(clone_id)


def manage_workforce():
    """Darwin's workforce management — spawn or kill based on queue depth.

    Called each Darwin cycle.
    Returns dict with actions taken.
    """
    queue = get_queue_depth()
    active = get_active_clone_count()
    total_workers = 1 + active  # primary + clones

    stats = {"queue_depth": queue, "active_clones": active, "spawned": 0, "terminated": 0}

    # Spawn if queue exceeds capacity (>3 tasks per worker)
    if queue > total_workers * 3 and total_workers < MAX_WORKERS:
        needed = min(queue // 3 - total_workers + 1, MAX_WORKERS - total_workers)
        for _ in range(needed):
            clone_id = spawn_clone()
            if clone_id:
                stats["spawned"] += 1

    # Kill clones if queue has drained (< 2 tasks and clones exist)
    elif queue < 2 and active > 0:
        # Kill one clone per cycle (gradual scale-down)
        oldest = list(_clones.keys())[0]
        terminate_clone(oldest)
        stats["terminated"] += 1

    if stats["spawned"] or stats["terminated"]:
        log.info(
            "Workforce: queue=%d, clones=%d, spawned=%d, terminated=%d",
            queue, active, stats["spawned"], stats["terminated"],
        )

    return stats
