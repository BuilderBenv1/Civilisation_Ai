import re
import requests
from typing import List, Dict
from shared.config import get_logger

logger = get_logger(__name__)

def crawl_layer3() -> List[Dict]:
    """
    Crawl Layer3.xyz for crypto bounties and tasks.
    
    Returns:
        List[Dict]: List of bounty dictionaries with platform, title, url, description, and platform-specific fields
    """
    bounties = []
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get('https://layer3.xyz', headers=headers, timeout=30)
        response.raise_for_status()
        
        html_content = response.text
        
        # Extract bounty/quest information using regex patterns
        quest_pattern = r'<div[^>]*class="[^"]*quest[^"]*"[^>]*>.*?</div>'
        title_pattern = r'<h[1-6][^>]*>([^<]+)</h[1-6]>'
        description_pattern = r'<p[^>]*>([^<]+)</p>'
        link_pattern = r'href="([^"]+)"'
        reward_pattern = r'(\$?\d+(?:,\d{3})*(?:\.\d{2})?|\d+\s*(?:USDC|ETH|BTC|tokens?))'
        
        quest_matches = re.findall(quest_pattern, html_content, re.DOTALL | re.IGNORECASE)
        
        for quest_html in quest_matches:
            try:
                title_match = re.search(title_pattern, quest_html, re.IGNORECASE)
                description_match = re.search(description_pattern, quest_html, re.IGNORECASE)
                link_match = re.search(link_pattern, quest_html)
                reward_match = re.search(reward_pattern, quest_html, re.IGNORECASE)
                
                if title_match:
                    title = title_match.group(1).strip()
                    description = description_match.group(1).strip() if description_match else ""
                    
                    # Construct full URL
                    url = link_match.group(1) if link_match else "https://layer3.xyz"
                    if url.startswith('/'):
                        url = f"https://layer3.xyz{url}"
                    elif not url.startswith('http'):
                        url = f"https://layer3.xyz/{url}"
                    
                    reward = reward_match.group(1) if reward_match else "Not specified"
                    
                    bounty = {
                        'platform': 'layer3',
                        'title': title,
                        'url': url,
                        'description': description,
                        'reward': reward,
                        'type': 'quest'
                    }
                    
                    bounties.append(bounty)
                    
            except Exception as e:
                logger.warning(f"Error parsing individual quest: {e}")
                continue
        
        # Fallback: look for general task/bounty patterns if no quests found
        if not bounties:
            task_patterns = [
                r'<div[^>]*class="[^"]*task[^"]*"[^>]*>.*?</div>',
                r'<div[^>]*class="[^"]*bounty[^"]*"[^>]*>.*?</div>',
                r'<div[^>]*class="[^"]*challenge[^"]*"[^>]*>.*?</div>'
            ]
            
            for pattern in task_patterns:
                task_matches = re.findall(pattern, html_content, re.DOTALL | re.IGNORECASE)
                
                for task_html in task_matches:
                    try:
                        title_match = re.search(title_pattern, task_html, re.IGNORECASE)
                        if title_match:
                            title = title_match.group(1).strip()
                            description_match = re.search(description_pattern, task_html, re.IGNORECASE)
                            description = description_match.group(1).strip() if description_match else ""
                            
                            bounty = {
                                'platform': 'layer3',
                                'title': title,
                                'url': 'https://layer3.xyz',
                                'description': description,
                                'reward': 'Not specified',
                                'type': 'task'
                            }
                            
                            bounties.append(bounty)
                            
                    except Exception as e:
                        logger.warning(f"Error parsing individual task: {e}")
                        continue
        
        logger.info(f"Successfully crawled {len(bounties)} bounties from Layer3")
        
    except requests.RequestException as e:
        logger.error(f"Network error while crawling Layer3: {e}")
    except Exception as e:
        logger.error(f"Unexpected error while crawling Layer3: {e}")
    
    return bounties