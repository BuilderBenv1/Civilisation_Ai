"""Anthropic Claude client with retry + structured output helpers."""

import time
import json
import anthropic
from shared.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, get_logger

log = get_logger("anthropic")

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        log.info("Anthropic client initialized (model=%s)", CLAUDE_MODEL)
    return _client


def ask(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    max_retries: int = 3,
) -> str:
    """Simple text completion with exponential backoff."""
    messages = [{"role": "user", "content": prompt}]
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = get_client().messages.create(
                model=model or CLAUDE_MODEL,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system if system else anthropic.NOT_GIVEN,
                messages=messages,
            )
            return resp.content[0].text
        except anthropic.RateLimitError as e:
            delay = 2 ** (attempt + 1)
            log.warning("Rate limited (attempt %d/%d), backing off %.1fs", attempt + 1, max_retries, delay)
            time.sleep(delay)
            last_err = e
        except anthropic.APIError as e:
            delay = 2 ** attempt
            log.warning("API error (attempt %d/%d): %s", attempt + 1, max_retries, e)
            time.sleep(delay)
            last_err = e
    raise last_err


def ask_json(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> dict | list:
    """Ask Claude and parse response as JSON. Strips markdown fences if present."""
    raw = ask(prompt, system=system, model=model, max_tokens=max_tokens, temperature=temperature)
    text = raw.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        lines = [l for l in lines[1:] if l.strip() != "```"]
        text = "\n".join(lines)
    return json.loads(text)
