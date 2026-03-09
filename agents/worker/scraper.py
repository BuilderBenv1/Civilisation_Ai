"""Worker skills — web scraping, data extraction, automation.

Each skill function takes a task description and returns results.
Uses Claude to generate and execute scraping/extraction plans.
"""

import json
import subprocess
import tempfile
import os
from pathlib import Path
from shared.config import get_logger
from shared.anthropic_client import ask, ask_json

log = get_logger("worker.scraper")


def scrape_url(url: str, extract_what: str = "all text content") -> dict:
    """Scrape a URL using a generated Python script with requests + BeautifulSoup."""
    script = ask(
        f"""Write a Python script that:
1. Fetches {url} using requests
2. Parses with BeautifulSoup
3. Extracts: {extract_what}
4. Prints the result as JSON to stdout

Use only: requests, bs4, json, re (standard libs + requests + bs4).
Include error handling. Print ONLY valid JSON.
Do not include any markdown formatting or explanation.""",
        system="You are a Python developer. Return ONLY the Python script, no explanation.",
        temperature=0.1,
    )

    return _run_generated_script(script, timeout=60)


def extract_structured_data(raw_text: str, schema_description: str) -> dict:
    """Use Claude to extract structured data from raw text."""
    result = ask_json(
        f"""Extract structured data from this text.

Text:
{raw_text[:4000]}

Desired schema: {schema_description}

Return the extracted data as JSON matching the described schema.""",
        temperature=0.1,
    )
    return result


def enrich_list(items: list[str], enrich_with: str) -> list[dict]:
    """Take a list of items and enrich each with additional data."""
    result = ask_json(
        f"""Enrich each item in this list with: {enrich_with}

Items:
{json.dumps(items[:100])}

Return a JSON array of objects, one per item, with the original value
and enriched fields.""",
        temperature=0.2,
    )
    return result if isinstance(result, list) else []


def build_automation(task_description: str) -> dict:
    """Generate and execute a simple automation pipeline."""
    # Plan the automation
    plan = ask_json(
        f"""Plan an automation for this task:

{task_description}

Return JSON:
{{
    "steps": ["step 1", "step 2", ...],
    "requires_playwright": true/false,
    "estimated_duration_seconds": number,
    "can_automate": true/false,
    "reason": "why or why not"
}}""",
        temperature=0.2,
    )

    if not plan.get("can_automate"):
        return {"success": False, "reason": plan.get("reason", "Cannot automate")}

    # Generate the script
    script = ask(
        f"""Write a Python script to automate this:
{task_description}

Steps to follow:
{json.dumps(plan.get('steps', []))}

Use requests/bs4 for web tasks. Print results as JSON to stdout.
Include error handling. No markdown, just the script.""",
        system="You are a Python developer. Return ONLY the Python script.",
        temperature=0.1,
    )

    result = _run_generated_script(script, timeout=120)
    result["plan"] = plan
    return result


def _run_generated_script(script: str, timeout: int = 60) -> dict:
    """Execute a generated Python script in a sandboxed subprocess."""
    # Strip any markdown code fences
    clean = script.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        lines = [l for l in lines[1:] if l.strip() != "```"]
        clean = "\n".join(lines)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(clean)
        script_path = f.name

    try:
        result = subprocess.run(
            ["python", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tempfile.gettempdir(),
        )

        if result.returncode != 0:
            log.warning("Script failed (exit %d): %s", result.returncode, result.stderr[:500])
            return {
                "success": False,
                "error": result.stderr[:1000],
                "stdout": result.stdout[:1000],
            }

        # Try to parse output as JSON
        stdout = result.stdout.strip()
        try:
            data = json.loads(stdout)
            return {"success": True, "data": data}
        except json.JSONDecodeError:
            return {"success": True, "data": stdout[:5000]}

    except subprocess.TimeoutExpired:
        log.warning("Script timed out after %ds", timeout)
        return {"success": False, "error": f"Timeout after {timeout}s"}
    except Exception as e:
        log.error("Script execution error: %s", e)
        return {"success": False, "error": str(e)}
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


# Skill registry — maps skill names to functions
SKILLS = {
    "scrape": scrape_url,
    "extract": extract_structured_data,
    "enrich": enrich_list,
    "automate": build_automation,
}
