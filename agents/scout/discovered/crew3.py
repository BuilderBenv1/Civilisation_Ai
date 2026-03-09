import re
import requests
from typing import List, Dict, Optional
from shared.config import get_logger

logger = get_logger(__name__)

def crawl_crew3() -> List[Dict]:
    """
    Crawl crew3.xyz for community tasks and crypto rewards.
    
    Returns:
        List[Dict]: List of task dictionaries with platform, title, url, description, and crew3-specific fields
    """
    tasks = []
    
    try:
        # Main page to get active communities/tasks
        response = requests.get(
            "https://crew3.xyz",
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            },
            timeout=30
        )
        response.raise_for_status()
        
        content = response.text
        
        # Extract community cards/tasks using regex patterns
        community_pattern = r'<div[^>]*class="[^"]*community[^"]*"[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>.*?<h[^>]*>([^<]+)</h[^>]*>.*?<p[^>]*>([^<]+)</p>'
        communities = re.findall(community_pattern, content, re.DOTALL | re.IGNORECASE)
        
        for community_url, title, description in communities:
            # Ensure full URL
            if community_url.startswith('/'):
                community_url = f"https://crew3.xyz{community_url}"
            
            # Extract additional details from community page
            try:
                community_response = requests.get(
                    community_url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    },
                    timeout=20
                )
                community_response.raise_for_status()
                
                community_content = community_response.text
                
                # Extract reward information
                reward_pattern = r'reward[^>]*>.*?(\d+(?:\.\d+)?)\s*([A-Z]{2,10})'
                rewards = re.findall(reward_pattern, community_content, re.IGNORECASE)
                
                # Extract task count
                task_count_pattern = r'(\d+)\s*tasks?'
                task_counts = re.findall(task_count_pattern, community_content, re.IGNORECASE)
                
                # Extract member count
                member_pattern = r'(\d+(?:,\d+)?)\s*members?'
                members = re.findall(member_pattern, community_content, re.IGNORECASE)
                
                task_dict = {
                    'platform': 'crew3',
                    'title': title.strip(),
                    'url': community_url,
                    'description': description.strip(),
                    'rewards': [{'amount': amount, 'token': token} for amount, token in rewards],
                    'task_count': int(task_counts[0]) if task_counts else None,
                    'member_count': int(members[0].replace(',', '')) if members else None,
                    'community_type': 'crypto_tasks'
                }
                
                tasks.append(task_dict)
                logger.info(f"Found crew3 community: {title}")
                
            except Exception as e:
                logger.warning(f"Error fetching community details for {community_url}: {e}")
                # Add basic task info even if details fail
                task_dict = {
                    'platform': 'crew3',
                    'title': title.strip(),
                    'url': community_url,
                    'description': description.strip(),
                    'rewards': [],
                    'task_count': None,
                    'member_count': None,
                    'community_type': 'crypto_tasks'
                }
                tasks.append(task_dict)
        
        # Also try to extract featured tasks from main page
        task_pattern = r'<div[^>]*class="[^"]*task[^"]*"[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>.*?<h[^>]*>([^<]+)</h[^>]*>.*?<p[^>]*>([^<]+)</p>'
        featured_tasks = re.findall(task_pattern, content, re.DOTALL | re.IGNORECASE)
        
        for task_url, task_title, task_desc in featured_tasks:
            if task_url.startswith('/'):
                task_url = f"https://crew3.xyz{task_url}"
            
            task_dict = {
                'platform': 'crew3',
                'title': task_title.strip(),
                'url': task_url,
                'description': task_desc.strip(),
                'rewards': [],
                'task_count': 1,
                'member_count': None,
                'community_type': 'featured_task'
            }
            tasks.append(task_dict)
            logger.info(f"Found crew3 featured task: {task_title}")
        
        logger.info(f"Successfully crawled {len(tasks)} tasks from crew3")
        return tasks
        
    except requests.RequestException as e:
        logger.error(f"Network error while crawling crew3: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error while crawling crew3: {e}")
        return []