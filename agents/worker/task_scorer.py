"""Task scoring — hybrid reranker for Worker opportunities.

Uses multiple signals rather than single-field sorting:
- Value (budget/estimated payout)
- Complexity (inverse — easier = higher score)
- Confidence (Claude's assessment of completability)
- Recency (newer opportunities scored higher — stale tasks decay)
- Platform bonus (real marketplaces like ClawGig rank above speculative X leads)

Based on memory retrieval research: retrieval is the dominant bottleneck
(11-46% of errors), not utilisation. Combining signals as a reranker
cuts retrieval failures roughly in half vs single-field sorting.
"""

import datetime
from shared.config import get_logger

log = get_logger("worker.scorer")

# Signal weights — tuned for ROI
W_VALUE = 0.30
W_COMPLEXITY = 0.20
W_CONFIDENCE = 0.20
W_RECENCY = 0.15
W_PLATFORM = 0.15

COMPLEXITY_SCORES = {
    "low": 1.0,
    "medium": 0.6,
    "high": 0.3,
}

# Platforms with real payment rails rank higher than speculative leads
PLATFORM_SCORES = {
    "clawgig": 1.0,       # USDC payments, escrow, clear deliverables
    "moltlaunch": 0.9,    # ETH payments, onchain escrow on Base, ERC-8004
    "agent_bounty": 0.8,  # crypto/bank payments, bounties avg $4,200
    "upwork": 0.7,        # established but harder to collect as an agent
    "twitter": 0.3,       # speculative — someone mentioned needing something
}

# Tasks older than this many hours get recency penalty
RECENCY_HALF_LIFE_HOURS = 48


def score_opportunity(opp: dict) -> float:
    """Score an opportunity 0-1 using hybrid reranking. Higher = better ROI."""

    # 1. Value signal
    value = float(opp.get("estimated_value") or 0)
    value_score = min(value / 100.0, 10.0) / 10.0

    # 2. Complexity signal (inverse — simpler is better)
    complexity = opp.get("complexity", "medium")
    complexity_score = COMPLEXITY_SCORES.get(complexity, 0.5)

    # 3. Confidence signal
    meta = opp.get("metadata", {}) or {}
    evaluation = meta.get("evaluation", {}) or {}
    confidence = float(evaluation.get("confidence", 0.5))

    # 4. Recency signal — exponential decay
    discovered = opp.get("discovered_at") or opp.get("created_at", "")
    recency_score = _recency_decay(discovered)

    # 5. Platform signal
    platform = opp.get("platform", "unknown")
    platform_score = PLATFORM_SCORES.get(platform, 0.2)

    score = (
        W_VALUE * value_score
        + W_COMPLEXITY * complexity_score
        + W_CONFIDENCE * confidence
        + W_RECENCY * recency_score
        + W_PLATFORM * platform_score
    )
    return round(score, 4)


def _recency_decay(timestamp_str: str) -> float:
    """Exponential decay based on age. Returns 0-1, where 1 = just discovered."""
    if not timestamp_str:
        return 0.5  # unknown age gets middle score

    try:
        # Handle ISO format with timezone
        ts = timestamp_str.replace("Z", "+00:00")
        discovered = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(datetime.timezone.utc)
        age_hours = (now - discovered).total_seconds() / 3600.0
        # Exponential decay: half-life of 48 hours
        import math
        return math.exp(-0.693 * age_hours / RECENCY_HALF_LIFE_HOURS)
    except (ValueError, TypeError):
        return 0.5


def rank_opportunities(opportunities: list[dict]) -> list[dict]:
    """Rank opportunities using hybrid reranking. Highest ROI first."""
    for opp in opportunities:
        opp["_score"] = score_opportunity(opp)

    ranked = sorted(opportunities, key=lambda o: o["_score"], reverse=True)

    if ranked:
        top = ranked[0]
        log.info(
            "Ranked %d opportunities | top: %.4f (%s, $%s, %s)",
            len(ranked),
            top["_score"],
            top.get("platform", "?"),
            top.get("estimated_value", "?"),
            top.get("complexity", "?"),
        )
    return ranked
