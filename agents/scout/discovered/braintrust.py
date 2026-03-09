import re
import requests
from typing import List, Dict
from shared.config import get_logger

logger = get_logger(__name__)

def crawl_braintrust() -> List[Dict]:
    """
    Crawl Braintrust platform for freelance opportunities.
    
    Returns:
        List[Dict]: List of job postings with platform, title, url, description, and platform-specific fields
    """
    jobs = []
    
    try:
        # Main jobs/projects page
        url = "https://braintrust.com/jobs"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        html_content = response.text
        
        # Extract job listings using regex patterns
        job_pattern = r'<div[^>]*class="[^"]*job[^"]*"[^>]*>.*?</div>'
        job_matches = re.findall(job_pattern, html_content, re.DOTALL | re.IGNORECASE)
        
        for job_html in job_matches:
            try:
                # Extract title
                title_match = re.search(r'<h[1-6][^>]*>([^<]+)</h[1-6]>', job_html)
                title = title_match.group(1).strip() if title_match else "No title"
                
                # Extract job URL
                url_match = re.search(r'href="([^"]*(?:job|project)[^"]*)"', job_html)
                job_url = url_match.group(1) if url_match else ""
                if job_url and not job_url.startswith('http'):
                    job_url = f"https://braintrust.com{job_url}"
                
                # Extract description
                desc_match = re.search(r'<p[^>]*>([^<]+)</p>', job_html)
                description = desc_match.group(1).strip() if desc_match else "No description"
                
                # Extract budget/rate if available
                budget_match = re.search(r'\$([0-9,]+(?:\.[0-9]{2})?)', job_html)
                budget = budget_match.group(1) if budget_match else None
                
                # Extract skills/tags
                skills_pattern = r'<span[^>]*class="[^"]*skill[^"]*"[^>]*>([^<]+)</span>'
                skills_matches = re.findall(skills_pattern, job_html, re.IGNORECASE)
                skills = [skill.strip() for skill in skills_matches]
                
                # Extract project type
                type_match = re.search(r'(hourly|fixed|contract)', job_html, re.IGNORECASE)
                project_type = type_match.group(1) if type_match else None
                
                if title and title != "No title":
                    job_data = {
                        'platform': 'braintrust',
                        'title': title,
                        'url': job_url,
                        'description': description,
                        'budget': budget,
                        'skills': skills,
                        'project_type': project_type,
                        'payment_method': 'crypto'
                    }
                    jobs.append(job_data)
                    
            except Exception as e:
                logger.warning(f"Error parsing individual job listing: {e}")
                continue
        
        # Try alternative scraping approach if no jobs found
        if not jobs:
            # Look for different HTML structure
            alt_pattern = r'<article[^>]*>.*?</article>'
            alt_matches = re.findall(alt_pattern, html_content, re.DOTALL)
            
            for article_html in alt_matches:
                try:
                    title_match = re.search(r'<h[1-6][^>]*>([^<]+)</h[1-6]>', article_html)
                    if title_match:
                        title = title_match.group(1).strip()
                        
                        url_match = re.search(r'href="([^"]+)"', article_html)
                        job_url = url_match.group(1) if url_match else ""
                        if job_url and not job_url.startswith('http'):
                            job_url = f"https://braintrust.com{job_url}"
                        
                        desc_match = re.search(r'<p[^>]*>([^<]+)</p>', article_html)
                        description = desc_match.group(1).strip() if desc_match else "No description"
                        
                        job_data = {
                            'platform': 'braintrust',
                            'title': title,
                            'url': job_url,
                            'description': description,
                            'budget': None,
                            'skills': [],
                            'project_type': None,
                            'payment_method': 'crypto'
                        }
                        jobs.append(job_data)
                        
                except Exception as e:
                    logger.warning(f"Error parsing alternative job listing: {e}")
                    continue
        
        logger.info(f"Successfully crawled {len(jobs)} jobs from Braintrust")
        
    except requests.RequestException as e:
        logger.error(f"Network error while crawling Braintrust: {e}")
    except Exception as e:
        logger.error(f"Unexpected error while crawling Braintrust: {e}")
    
    return jobs