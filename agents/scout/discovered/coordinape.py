import requests
from typing import List, Dict, Optional
from shared.config import get_logger

logger = get_logger(__name__)

def crawl_coordinape() -> List[Dict]:
    """
    Crawl Coordinape platform for decentralized compensation opportunities and task-based rewards.
    
    Returns:
        List[Dict]: List of opportunities with platform, title, url, description and platform-specific fields
    """
    opportunities = []
    
    try:
        # Coordinape API endpoints for circles and epochs
        base_url = "https://api.coordinape.com"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        # Get active circles
        circles_response = requests.get(
            f"{base_url}/api/circles",
            headers=headers,
            timeout=30
        )
        
        if circles_response.status_code != 200:
            logger.warning(f"Failed to fetch circles: {circles_response.status_code}")
            return opportunities
            
        circles_data = circles_response.json()
        
        for circle in circles_data.get('circles', []):
            if not circle.get('active', False):
                continue
                
            circle_id = circle.get('id')
            circle_name = circle.get('name', 'Unknown Circle')
            
            try:
                # Get epochs for this circle
                epochs_response = requests.get(
                    f"{base_url}/api/circles/{circle_id}/epochs",
                    headers=headers,
                    timeout=30
                )
                
                if epochs_response.status_code == 200:
                    epochs_data = epochs_response.json()
                    
                    for epoch in epochs_data.get('epochs', []):
                        if epoch.get('ended', True):
                            continue
                            
                        opportunity = {
                            'platform': 'coordinape',
                            'title': f"{circle_name} - {epoch.get('description', 'Active Epoch')}",
                            'url': f"https://coordinape.com/circles/{circle_id}",
                            'description': f"Participate in {circle_name} circle for decentralized compensation. "
                                         f"Epoch: {epoch.get('description', 'Current epoch')}",
                            'circle_id': circle_id,
                            'circle_name': circle_name,
                            'epoch_id': epoch.get('id'),
                            'start_date': epoch.get('start_date'),
                            'end_date': epoch.get('end_date'),
                            'token_name': circle.get('token_name'),
                            'vouching': circle.get('vouching', False),
                            'min_vouches': circle.get('min_vouches', 0),
                            'nomination_days_limit': circle.get('nomination_days_limit'),
                            'only_giver_vouch': circle.get('only_giver_vouch', False)
                        }
                        
                        opportunities.append(opportunity)
                        
            except requests.exceptions.RequestException as e:
                logger.warning(f"Error fetching epochs for circle {circle_id}: {e}")
                continue
                
        # Also check for public opportunities
        try:
            public_response = requests.get(
                f"{base_url}/api/public/circles",
                headers=headers,
                timeout=30
            )
            
            if public_response.status_code == 200:
                public_data = public_response.json()
                
                for circle in public_data.get('circles', []):
                    if circle.get('visible', False) and circle.get('active', False):
                        opportunity = {
                            'platform': 'coordinape',
                            'title': f"Join {circle.get('name', 'Public Circle')}",
                            'url': f"https://coordinape.com/circles/{circle.get('id')}",
                            'description': f"Join public circle: {circle.get('name')}. "
                                         f"{circle.get('description', 'Decentralized compensation opportunity')}",
                            'circle_id': circle.get('id'),
                            'circle_name': circle.get('name'),
                            'is_public': True,
                            'token_name': circle.get('token_name'),
                            'vouching': circle.get('vouching', False),
                            'min_vouches': circle.get('min_vouches', 0)
                        }
                        
                        opportunities.append(opportunity)
                        
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error fetching public circles: {e}")
            
        logger.info(f"Successfully crawled {len(opportunities)} opportunities from Coordinape")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error while crawling Coordinape: {e}")
    except Exception as e:
        logger.error(f"Unexpected error while crawling Coordinape: {e}")
        
    return opportunities