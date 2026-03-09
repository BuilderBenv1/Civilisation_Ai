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
    if not url or not url.startswith(('http://', 'https://')):
        return {"success": False, "error": "Invalid URL provided"}
    
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
    if not raw_text or not raw_text.strip():
        return {"success": False, "error": "No text provided for extraction"}
    
    result = ask_json(
        f"""Extract structured data from this text.

Text:
{raw_text[:4000]}

Desired schema: {schema_description}

Return the extracted data as JSON matching the described schema.""",
        temperature=0.1,
    )
    return {"success": True, "data": result}


def enrich_list(items: list[str], enrich_with: str) -> list[dict]:
    """Take a list of items and enrich each with additional data."""
    if not items or not isinstance(items, list):
        return {"success": False, "error": "Invalid items list provided"}
    
    if len(items) > 100:
        items = items[:100]  # Limit to prevent excessive API usage
    
    result = ask_json(
        f"""Enrich each item in this list with: {enrich_with}

Items:
{json.dumps(items)}

Return a JSON array of objects, one per item, with the original value
and enriched fields.""",
        temperature=0.2,
    )
    
    if isinstance(result, list):
        return {"success": True, "data": result}
    else:
        return {"success": False, "error": "Failed to generate enriched list"}


def build_automation(task_description: str) -> dict:
    """Generate and execute a simple automation pipeline."""
    if not task_description or not task_description.strip():
        return {"success": False, "error": "No task description provided"}
    
    # Plan the automation
    plan = ask_json(
        f"""Plan an automation for this task:

{task_description}

Return JSON:
{{
    "steps": ["step 1", "step 2", ...],
    "requires_playwright": true/false,
    "estimated_duration_seconds": number,
    "python_script": "complete Python script to execute this automation"
}}

The Python script should use only standard libraries + requests + bs4.
Include error handling and print results as JSON.""",
        temperature=0.2,
    )
    
    if not isinstance(plan, dict) or "python_script" not in plan:
        return {"success": False, "error": "Failed to generate automation plan"}
    
    script = plan.get("python_script", "")
    if not script:
        return {"success": False, "error": "No script generated in automation plan"}
    
    # Execute the generated script
    result = _run_generated_script(script, timeout=120)
    
    if result.get("success"):
        result["automation_plan"] = {
            "steps": plan.get("steps", []),
            "estimated_duration": plan.get("estimated_duration_seconds", 0)
        }
    
    return result


def _run_generated_script(script: str, timeout: int = 60) -> dict:
    """Execute a generated Python script safely with enhanced error handling."""
    if not script or not script.strip():
        return {"success": False, "error": "Empty script provided"}
    
    # Basic safety checks
    dangerous_patterns = [
        "import os", "import subprocess", "import sys", "__import__",
        "eval(", "exec(", "open(", "file(", "input(", "raw_input(",
        "rm ", "del ", "rmdir", "unlink", "remove",
    ]
    
    script_lower = script.lower()
    for pattern in dangerous_patterns:
        if pattern in script_lower:
            log.warning("Script blocked due to dangerous pattern: %s", pattern)
            return {"success": False, "error": f"Script contains dangerous pattern: {pattern}"}
    
    # Clean up the script - remove markdown formatting if present
    lines = script.split('\n')
    cleaned_lines = []
    in_code_block = False
    
    for line in lines:
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            continue
        if not in_code_block and line.strip().startswith('```'):
            continue
        cleaned_lines.append(line)
    
    cleaned_script = '\n'.join(cleaned_lines).strip()
    
    # Validate that it looks like Python code
    if not any(keyword in cleaned_script for keyword in ['import ', 'def ', 'print(', 'return']):
        return {"success": False, "error": "Generated text does not appear to be valid Python code"}
    
    script_path = None
    try:
        # Write script to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(cleaned_script)
            script_path = f.name
        
        log.info("Executing generated script (timeout=%ds)", timeout)
        
        # Execute with timeout
        result = subprocess.run(
            ["python3", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tempfile.gettempdir(),  # Run in safe directory
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Script execution failed"
            log.error("Script execution failed: %s", error_msg)
            return {"success": False, "error": f"Script error: {error_msg}"}
        
        output = result.stdout.strip()
        if not output:
            return {"success": False, "error": "Script produced no output"}
        
        # Try to parse as JSON
        try:
            data = json.loads(output)
            return {"success": True, "data": data, "raw_output": output}
        except json.JSONDecodeError as e:
            # If not valid JSON, return as text
            log.warning("Script output is not valid JSON: %s", e)
            return {"success": True, "data": output, "raw_output": output, "note": "Output is not JSON"}
    
    except subprocess.TimeoutExpired:
        log.warning("Script timed out after %ds", timeout)
        return {"success": False, "error": f"Timeout after {timeout}s"}
    except FileNotFoundError:
        return {"success": False, "error": "Python3 not found - cannot execute scripts"}
    except PermissionError:
        return {"success": False, "error": "Permission denied - cannot execute script"}
    except Exception as e:
        log.error("Script execution error: %s", e)
        return {"success": False, "error": f"Execution error: {str(e)}"}
    finally:
        # Clean up temporary file
        if script_path:
            try:
                os.unlink(script_path)
            except OSError as e:
                log.warning("Failed to clean up script file %s: %s", script_path, e)


# Skill registry — maps skill names to functions
SKILLS = {
    "scrape": scrape_url,
    "extract": extract_structured_data,
    "enrich": enrich_list,
    "automate": build_automation,
}