import re
import requests
from typing import List, Dict, Optional
from shared.config import get_logger

logger = get_logger(__name__)

def crawl_wonderverse() -> List[Dict]:
    """
    Crawl Wonderverse DAO task marketplace for bounties and tasks.
    
    Returns:
        List[Dict]: List of task/bounty dictionaries with platform, title, url, description, and platform-specific fields
    """
    results = []
    
    try:
        base_url = "https://wonderverse.xyz"
        
        # Get main page
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(base_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        html_content = response.text
        
        # Extract task/bounty links - look for common patterns
        task_patterns = [
            r'href="([^"]*(?:task|bounty|quest|mission)[^"]*)"',
            r'href="(/[^"]*)"[^>]*(?:class="[^"]*(?:task|bounty|quest|card)[^"]*")',
        ]
        
        task_urls = set()
        for pattern in task_patterns:
            matches = re.findall(pattern, html_content, re.IGNORECASE)
            for match in matches:
                if match.startswith('/'):
                    task_urls.add(base_url + match)
                elif match.startswith('http'):
                    task_urls.add(match)
        
        # Extract task information from main page
        title_patterns = [
            r'<h[1-6][^>]*class="[^"]*(?:title|heading|name)[^"]*"[^>]*>([^<]+)</h[1-6]>',
            r'<div[^>]*class="[^"]*(?:title|heading|name)[^"]*"[^>]*>([^<]+)</div>',
            r'<span[^>]*class="[^"]*(?:title|heading|name)[^"]*"[^>]*>([^<]+)</span>',
        ]
        
        description_patterns = [
            r'<p[^>]*class="[^"]*(?:description|summary|content)[^"]*"[^>]*>([^<]+)</p>',
            r'<div[^>]*class="[^"]*(?:description|summary|content)[^"]*"[^>]*>([^<]+)</div>',
        ]
        
        # Try to extract structured data from the page
        card_pattern = r'<(?:div|article)[^>]*class="[^"]*(?:card|item|task|bounty)[^"]*"[^>]*>(.*?)</(?:div|article)>'
        cards = re.findall(card_pattern, html_content, re.DOTALL | re.IGNORECASE)
        
        for i, card in enumerate(cards[:20]):  # Limit to first 20 items
            title = None
            description = None
            url = None
            
            # Extract title from card
            for pattern in title_patterns:
                title_match = re.search(pattern, card, re.IGNORECASE)
                if title_match:
                    title = title_match.group(1).strip()
                    break
            
            # Extract description from card
            for pattern in description_patterns:
                desc_match = re.search(pattern, card, re.IGNORECASE)
                if desc_match:
                    description = desc_match.group(1).strip()
                    break
            
            # Extract URL from card
            url_match = re.search(r'href="([^"]+)"', card)
            if url_match:
                url = url_match.group(1)
                if url.startswith('/'):
                    url = base_url + url
            
            # Extract reward/bounty amount if present
            reward_patterns = [
                r'(\$[\d,]+(?:\.\d{2})?)',
                r'([\d,]+(?:\.\d+)?\s*(?:USD|USDC|ETH|tokens?))',
                r'reward[^>]*>([^<]+)',
            ]
            
            reward = None
            for pattern in reward_patterns:
                reward_match = re.search(pattern, card, re.IGNORECASE)
                if reward_match:
                    reward = reward_match.group(1).strip()
                    break
            
            # Extract category/type if present
            category_patterns = [
                r'category[^>]*>([^<]+)',
                r'type[^>]*>([^<]+)',
                r'tag[^>]*>([^<]+)',
            ]
            
            category = None
            for pattern in category_patterns:
                cat_match = re.search(pattern, card, re.IGNORECASE)
                if cat_match:
                    category = cat_match.group(1).strip()
                    break
            
            if title:
                task_data = {
                    'platform': 'wonderverse',
                    'title': title,
                    'url': url or base_url,
                    'description': description or 'No description available',
                    'reward': reward,
                    'category': category,
                    'source_type': 'web_scraping'
                }
                results.append(task_data)
        
        # If no structured cards found, try to get basic page info
        if not results:
            page_title_match = re.search(r'<title>([^<]+)</title>', html_content)
            page_title = page_title_match.group(1).strip() if page_title_match else "Wonderverse Tasks"
            
            meta_desc_match = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]+)"', html_content)
            meta_desc = meta_desc_match.group(1).strip() if meta_desc_match else "DAO task marketplace with bounties for contributors"
            
            results.append({
                'platform': 'wonderverse',
                'title': page_title,
                'url': base_url,
                'description': meta_desc,
                'reward': None,
                'category': 'marketplace',
                'source_type': 'web_scraping'
            })
        
        logger.info(f"Successfully crawled {len(results)} items from Wonderverse")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error while crawling Wonderverse: {e}")
    except Exception as e:
        logger.error(f"Unexpected error while crawling Wonderverse: {e}")
    
    return results