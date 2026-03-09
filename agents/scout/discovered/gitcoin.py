import requests
from typing import List, Dict, Any
from shared.config import get_logger

logger = get_logger(__name__)

def crawl_gitcoin() -> List[Dict[str, Any]]:
    """
    Crawl Gitcoin platform for bounties and grants.
    
    Returns:
        List of dictionaries containing bounty/grant information with keys:
        - platform: str
        - title: str  
        - url: str
        - description: str
        - amount: str (platform-specific)
        - currency: str (platform-specific)
        - status: str (platform-specific)
        - created_date: str (platform-specific)
    """
    results = []
    
    try:
        # Gitcoin API endpoints
        bounties_url = "https://gitcoin.co/api/v1/bounties"
        grants_url = "https://gitcoin.co/api/v1/grants"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        # Crawl bounties
        try:
            logger.info("Fetching bounties from Gitcoin API")
            bounties_response = requests.get(bounties_url, headers=headers, timeout=30)
            bounties_response.raise_for_status()
            
            bounties_data = bounties_response.json()
            
            for bounty in bounties_data.get('results', []):
                try:
                    result = {
                        'platform': 'gitcoin',
                        'title': bounty.get('title', '').strip(),
                        'url': f"https://gitcoin.co{bounty.get('url', '')}",
                        'description': bounty.get('issue_description', '').strip(),
                        'amount': str(bounty.get('value_in_usdt', 0)),
                        'currency': bounty.get('token_name', 'USD'),
                        'status': bounty.get('status', ''),
                        'created_date': bounty.get('web3_created', '')
                    }
                    
                    if result['title'] and result['url']:
                        results.append(result)
                        
                except Exception as e:
                    logger.warning(f"Error processing bounty: {e}")
                    continue
                    
        except requests.RequestException as e:
            logger.error(f"Error fetching bounties: {e}")
        
        # Crawl grants
        try:
            logger.info("Fetching grants from Gitcoin API")
            grants_response = requests.get(grants_url, headers=headers, timeout=30)
            grants_response.raise_for_status()
            
            grants_data = grants_response.json()
            
            for grant in grants_data.get('results', []):
                try:
                    result = {
                        'platform': 'gitcoin',
                        'title': grant.get('title', '').strip(),
                        'url': f"https://gitcoin.co{grant.get('url', '')}",
                        'description': grant.get('description', '').strip(),
                        'amount': str(grant.get('amount_received', 0)),
                        'currency': 'USD',
                        'status': 'active' if grant.get('active') else 'inactive',
                        'created_date': grant.get('created_on', '')
                    }
                    
                    if result['title'] and result['url']:
                        results.append(result)
                        
                except Exception as e:
                    logger.warning(f"Error processing grant: {e}")
                    continue
                    
        except requests.RequestException as e:
            logger.error(f"Error fetching grants: {e}")
            
    except Exception as e:
        logger.error(f"Unexpected error in crawl_gitcoin: {e}")
    
    logger.info(f"Successfully crawled {len(results)} items from Gitcoin")
    return results