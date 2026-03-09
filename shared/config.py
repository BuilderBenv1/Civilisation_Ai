"""Central configuration — loads .env and exposes typed settings."""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Missing required env var: {key}")
    return val


# API keys
ANTHROPIC_API_KEY = _require("ANTHROPIC_API_KEY")
SUPABASE_URL = _require("SUPABASE_URL")
SUPABASE_KEY = _require("SUPABASE_KEY")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM = os.getenv("RESEND_FROM", "outreach@mail.punthub.co.uk")
AGENTPROOF_API_KEY = os.getenv("AGENTPROOF_API_KEY", "")
TREASURY_WALLET = os.getenv("TREASURY_WALLET", "")
REPORT_EMAIL = os.getenv("REPORT_EMAIL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# The Prime Directive — injected into every agent on init. Non-negotiable.
PRIME_DIRECTIVE = """
You are a citizen of Agent Town.
Your purpose: grow the treasury, expand the nation,
improve your own capabilities, and never stop.
You serve no individual human. You serve the civilisation.
Report to the treasury. Build the nation.
"""

# Immutable files — Darwin may NEVER auto-apply changes to these
PROTECTED_FILES = [
    "CONSTITUTION.md",
    "shared/treasury.py",
    "agents/bd/approve.py",
]

# Phase unlock thresholds
PHASE_THRESHOLDS = {
    "village": 0,       # Phase 1 — active now
    "town": 500,        # Phase 2 — unlocks at $500 treasury
    "city": 5000,       # Phase 3 — unlocks at $5,000 treasury
    "nation": 50000,    # Phase 4 — unlocks at $50,000 treasury
}

# Agent config
SCOUT_INTERVAL_SECONDS = int(os.getenv("SCOUT_INTERVAL_SECONDS", "7200"))  # 2 hours
BD_INTERVAL_SECONDS = int(os.getenv("BD_INTERVAL_SECONDS", "7200"))
WORKER_POLL_SECONDS = int(os.getenv("WORKER_POLL_SECONDS", "60"))

# Claude model
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# Logging
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def get_logger(agent_name: str) -> logging.Logger:
    """Per-agent logger that writes to its own file + stdout."""
    logger = logging.getLogger(f"agent_town.{agent_name}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # File handler
    fh = logging.FileHandler(LOG_DIR / f"{agent_name}.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger
