import re
import requests
from typing import List, Dict, Optional
from shared.config import get_logger

logger = get_logger(__name__)

def crawl_dework() -> List[Dict]:
    """
    Crawl Dework platform for Web3 tasks and bounties.
    
    Returns:
        List[Dict]: List of task dictionaries with platform, title, url, description, and platform-specific fields
    """
    tasks = []
    
    try:
        # Main page to get task listings
        url = "https://dework.xyz"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        html_content = response.text
        
        # Extract task information using regex patterns
        # Look for task cards or listings in the HTML
        task_pattern = r'<div[^>]*class="[^"]*task[^"]*"[^>]*>.*?</div>'
        task_matches = re.findall(task_pattern, html_content, re.DOTALL | re.IGNORECASE)
        
        # Extract titles
        title_pattern = r'<h[1-6][^>]*>([^<]+)</h[1-6]>|<div[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</div>'
        
        # Extract links
        link_pattern = r'href="([^"]*(?:task|bounty)[^"]*)"'
        
        # Extract descriptions
        desc_pattern = r'<p[^>]*>([^<]+)</p>|<div[^>]*class="[^"]*description[^"]*"[^>]*>([^<]+)</div>'
        
        # Extract reward/bounty amounts
        reward_pattern = r'(\$?\d+(?:\.\d+)?(?:\s*(?:USD|USDC|ETH|BTC|[A-Z]{2,5}))?)(?:\s*(?:reward|bounty|prize))?'
        
        titles = re.findall(title_pattern, html_content, re.IGNORECASE)
        links = re.findall(link_pattern, html_content, re.IGNORECASE)
        descriptions = re.findall(desc_pattern, html_content, re.IGNORECASE)
        rewards = re.findall(reward_pattern, html_content, re.IGNORECASE)
        
        # Process extracted data
        max_items = max(len(titles), len(links), len(descriptions))
        
        for i in range(min(max_items, 50)):  # Limit to 50 items
            try:
                title = ""
                if i < len(titles):
                    title_tuple = titles[i]
                    title = title_tuple[0] if title_tuple[0] else title_tuple[1] if len(title_tuple) > 1 else ""
                
                task_url = ""
                if i < len(links):
                    task_url = links[i]
                    if not task_url.startswith('http'):
                        task_url = f"https://dework.xyz{task_url}"
                
                description = ""
                if i < len(descriptions):
                    desc_tuple = descriptions[i]
                    description = desc_tuple[0] if desc_tuple[0] else desc_tuple[1] if len(desc_tuple) > 1 else ""
                
                reward = ""
                if i < len(rewards):
                    reward = rewards[i]
                
                # Clean up extracted text
                title = re.sub(r'\s+', ' ', title).strip()
                description = re.sub(r'\s+', ' ', description).strip()
                
                if title and len(title) > 3:  # Only include tasks with meaningful titles
                    task = {
                        'platform': 'dework',
                        'title': title,
                        'url': task_url or url,
                        'description': description,
                        'reward': reward,
                        'task_type': 'bounty',
                        'status': 'open'
                    }
                    tasks.append(task)
                    
            except Exception as e:
                logger.warning(f"Error processing task {i}: {str(e)}")
                continue
        
        # If no tasks found with main pattern, try alternative extraction
        if not tasks:
            # Look for any links that might be tasks
            all_links = re.findall(r'href="([^"]+)"[^>]*>([^<]+)</a>', html_content)
            
            for link_url, link_text in all_links[:20]:  # Limit to 20 items
                if any(keyword in link_text.lower() for keyword in ['task', 'bounty', 'project', 'job']):
                    full_url = link_url if link_url.startswith('http') else f"https://dework.xyz{link_url}"
                    
                    task = {
                        'platform': 'dework',
                        'title': link_text.strip(),
                        'url': full_url,
                        'description': '',
                        'reward': '',
                        'task_type': 'task',
                        'status': 'open'
                    }
                    tasks.append(task)
        
        logger.info(f"Successfully crawled {len(tasks)} tasks from Dework")
        
    except requests.RequestException as e:
        logger.error(f"Network error while crawling Dework: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error while crawling Dework: {str(e)}")
    
    return tasks