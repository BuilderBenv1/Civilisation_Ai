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
    
    # Pre-validate URL accessibility
    try:
        import requests
        test_response = requests.head(url, timeout=10, allow_redirects=True)
        if test_response.status_code >= 400:
            return {"success": False, "error": f"URL returned {test_response.status_code}"}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"URL not accessible: {str(e)}"}
    
    script = ask(
        f"""Write a Python script that:
1. Fetches {url} using requests with proper headers and timeout
2. Parses with BeautifulSoup
3. Extracts: {extract_what}
4. Prints the result as JSON to stdout
5. Handles common errors: timeouts, 404s, parsing failures
6. Uses User-Agent header to avoid blocking
7. Limits response size to prevent memory issues

Use only: requests, bs4, json, re (standard libs + requests + bs4).
Include comprehensive error handling for network and parsing errors.
Print ONLY valid JSON with success/error fields.
Do not include any markdown formatting or explanation.""",
        system="You are a Python developer. Return ONLY the Python script, no explanation. Focus on robust error handling.",
        temperature=0.1,
    )

    return _run_generated_script(script, timeout=90)  # Increased timeout for complex scraping


def extract_structured_data(raw_text: str, schema_description: str) -> dict:
    """Use Claude to extract structured data from raw text."""
    if not raw_text or not raw_text.strip():
        return {"success": False, "error": "No text provided for extraction"}
    
    # Validate text length and content
    if len(raw_text) > 50000:
        raw_text = raw_text[:50000] + "... [truncated]"
        log.warning("Text truncated to 50k chars for extraction")
    
    try:
        result = ask_json(
            f"""Extract structured data from this text.

Text:
{raw_text[:4000]}

Desired schema: {schema_description}

Return the extracted data as JSON matching the described schema.""",
            temperature=0.1,
        )
        return {"success": True, "data": result}
    except Exception as e:
        log.error("Data extraction failed: %s", e)
        return {"success": False, "error": f"Extraction failed: {str(e)}"}


def enrich_list(items: list[str], enrich_with: str) -> list[dict]:
    """Take a list of items and enrich each with additional data."""
    if not items or not isinstance(items, list):
        return {"success": False, "error": "Invalid items list provided"}
    
    if len(items) > 100:
        items = items[:100]  # Limit to prevent excessive API usage
    
    try:
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
            return {"success": False, "error": "Invalid response format from enrichment"}
    except Exception as e:
        log.error("List enrichment failed: %s", e)
        return {"success": False, "error": f"Enrichment failed: {str(e)}"}


def build_automation(task_description: str) -> dict:
    """Generate and execute an automation script based on task description."""
    if not task_description or len(task_description.strip()) < 10:
        return {"success": False, "error": "Task description too short or empty"}
    
    # Safety check for dangerous operations
    dangerous_keywords = ['delete', 'remove', 'rm ', 'drop table', 'format', 'shutdown']
    if any(keyword in task_description.lower() for keyword in dangerous_keywords):
        return {"success": False, "error": "Task contains potentially dangerous operations"}
    
    try:
        script = ask(
            f"""Create a Python automation script for this task:
{task_description}

Requirements:
- Use only standard libraries and requests, bs4 if needed
- Include comprehensive error handling
- Print results as JSON to stdout
- No file system modifications outside /tmp
- No network operations to internal/private IPs
- Include progress logging

Return ONLY the Python script, no explanation.""",
            system="You are a Python automation expert. Focus on safe, robust code with excellent error handling.",
            temperature=0.2,
        )
        
        return _run_generated_script(script, timeout=120)
    except Exception as e:
        log.error("Automation script generation failed: %s", e)
        return {"success": False, "error": f"Script generation failed: {str(e)}"}


def _run_generated_script(script: str, timeout: int = 60) -> dict:
    """Execute a generated Python script safely and return results."""
    if not script or not script.strip():
        return {"success": False, "error": "Empty script provided"}
    
    # Enhanced security checks
    dangerous_imports = ['os.system', 'subprocess.call', 'eval(', 'exec(', '__import__', 'open(']
    script_lower = script.lower()
    for danger in dangerous_imports:
        if danger in script_lower:
            log.warning("Blocked dangerous operation in script: %s", danger)
            return {"success": False, "error": f"Script contains blocked operation: {danger}"}
    
    script_path = None
    try:
        # Create temporary script file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            # Add safety imports and error handling wrapper
            safe_script = f"""#!/usr/bin/env python3
import json
import sys
try:
{chr(10).join('    ' + line for line in script.split(chr(10)))}
except Exception as e:
    print(json.dumps({{"success": False, "error": str(e)}}))
    sys.exit(1)
"""
            f.write(safe_script)
            script_path = f.name
        
        # Execute with resource limits
        result = subprocess.run(
            ["python3", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/tmp",  # Run in safe directory
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Script execution failed"
            log.error("Script execution failed: %s", error_msg)
            return {"success": False, "error": error_msg}
        
        # Parse JSON output
        try:
            output = result.stdout.strip()
            if not output:
                return {"success": False, "error": "Script produced no output"}
            
            # Try to parse as JSON first
            try:
                parsed = json.loads(output)
                return parsed if isinstance(parsed, dict) else {"success": True, "data": parsed}
            except json.JSONDecodeError:
                # If not JSON, wrap as successful text result
                return {"success": True, "data": output}
                
        except Exception as e:
            log.error("Failed to parse script output: %s", e)
            return {"success": False, "error": f"Output parsing failed: {str(e)}"}
    
    except subprocess.TimeoutExpired:
        log.error("Script execution timed out after %d seconds", timeout)
        return {"success": False, "error": f"Script timed out after {timeout} seconds"}
    except PermissionError:
        log.error("Permission denied executing script")
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