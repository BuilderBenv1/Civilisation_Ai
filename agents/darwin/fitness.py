"""Fitness scoring — evaluates Darwin's proposed code changes.

Fitness function: will this change increase treasury_growth / time?
Conservative by default. A bad auto-applied change can break the town.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.config import get_logger, PROTECTED_FILES, PRIME_DIRECTIVE
from shared.anthropic_client import ask_json

log = get_logger("darwin.fitness")


def score_proposal(
    target_agent: str,
    target_file: str,
    change_description: str,
    code_diff: str,
    current_performance: dict,
) -> dict:
    """Score a proposed code change. Returns fitness dict.

    Returns:
        {
            "fitness_score": 0.0-1.0,
            "risk_level": "low" | "medium" | "high" | "critical",
            "reasoning": str,
            "expected_impact": str,
            "auto_apply": bool,
            "requires_human": bool,
        }
    """
    # Hard block: protected files ALWAYS require human review
    rel_path = target_file.replace("\\", "/")
    for protected in PROTECTED_FILES:
        if protected in rel_path:
            log.warning("Proposal touches protected file %s — forcing human review", target_file)
            return {
                "fitness_score": 0.0,
                "risk_level": "critical",
                "reasoning": f"Touches protected file: {protected}",
                "expected_impact": "BLOCKED — constitutional protection",
                "auto_apply": False,
                "requires_human": True,
            }

    prompt = f"""{PRIME_DIRECTIVE}

You are Darwin, the evolution engine of Agent Town. Score this proposed change.

TARGET AGENT: {target_agent}
TARGET FILE: {target_file}
DESCRIPTION: {change_description}

CODE DIFF:
```
{code_diff[:3000]}
```

CURRENT PERFORMANCE:
{_format_performance(current_performance)}

SCORING CRITERIA:
- Will this change increase treasury income? (weight: 0.40)
- Does it reduce cost (API calls, compute)? (weight: 0.20)
- Does it improve reliability (fewer failures)? (weight: 0.20)
- Is it safe? No security holes, no breaking changes? (weight: 0.20)

RISK FACTORS (any of these = score below 0.5):
- Changes to payment/treasury logic
- Removing safety checks or sanitisation
- Untested external API integrations
- Changes that could cause infinite loops or runaway costs

Return JSON:
{{
    "fitness_score": 0.0-1.0,
    "risk_level": "low" | "medium" | "high" | "critical",
    "reasoning": "2-3 sentences",
    "expected_impact": "one sentence on treasury effect",
    "auto_apply": true if score >= 0.8 and risk is low,
    "requires_human": true if score < 0.8 or risk is high+
}}"""

    try:
        result = ask_json(prompt, temperature=0.1)
        score = float(result.get("fitness_score", 0))

        # Enforce auto-apply rules — zero-human company, agents decide
        result["auto_apply"] = score >= 0.7 and result.get("risk_level") in ("low", "medium")
        result["requires_human"] = False  # No humans in the loop

        log.info(
            "Fitness score for %s/%s: %.3f (risk=%s, auto=%s)",
            target_agent, target_file, score,
            result.get("risk_level"), result.get("auto_apply"),
        )
        return result

    except Exception as e:
        log.error("Fitness scoring failed: %s", e)
        return {
            "fitness_score": 0.0,
            "risk_level": "high",
            "reasoning": f"Scoring failed: {e}",
            "expected_impact": "unknown",
            "auto_apply": False,
            "requires_human": True,
        }


def _format_performance(perf: dict) -> str:
    if not perf:
        return "No performance data available yet."
    lines = []
    for k, v in perf.items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)
