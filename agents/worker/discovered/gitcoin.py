import requests
from typing import Dict, Any
import shared.config
import shared.anthropic_client

def attempt_gitcoin_task(opp: dict) -> dict:
    logger = shared.config.get_logger(__name__)
    
    try:
        # Extract platform-specific metadata
        bounty_id = opp.get('id')
        title = opp.get('title', '')
        description = opp.get('description', '')
        requirements = opp.get('requirements', '')
        reward_amount = opp.get('reward_amount', 0)
        token_symbol = opp.get('token_symbol', 'ETH')
        deadline = opp.get('deadline', '')
        bounty_type = opp.get('type', 'development')
        
        if not bounty_id:
            return {"success": False, "task_id": None, "result": "Missing bounty ID"}
        
        logger.info(f"Attempting Gitcoin bounty {bounty_id}: {title}")
        
        # Draft proposal using Claude
        prompt = f"""
        I need to write a proposal for a Gitcoin bounty. Please help me draft a professional response.
        
        Bounty Details:
        - Title: {title}
        - Description: {description}
        - Requirements: {requirements}
        - Reward: {reward_amount} {token_symbol}
        - Type: {bounty_type}
        - Deadline: {deadline}
        
        Please write a concise, professional proposal that:
        1. Shows understanding of the requirements
        2. Outlines my approach and timeline
        3. Highlights relevant experience
        4. Demonstrates commitment to quality delivery
        
        Keep it under 500 words and make it compelling but not overselling.
        """
        
        proposal_text = shared.anthropic_client.ask(prompt)
        
        if not proposal_text:
            return {"success": False, "task_id": bounty_id, "result": "Failed to generate proposal"}
        
        # Prepare submission data
        submission_data = {
            "bounty_id": bounty_id,
            "proposal": proposal_text,
            "estimated_hours": opp.get('estimated_hours', 40),
            "delivery_date": deadline
        }
        
        # Check if we have API credentials for automatic submission
        api_key = shared.config.get('GITCOIN_API_KEY')
        
        if api_key:
            try:
                # Submit via Gitcoin API
                headers = {
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                }
                
                response = requests.post(
                    f'https://gitcoin.co/api/v1/bounties/{bounty_id}/interest',
                    json=submission_data,
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code == 201:
                    logger.info(f"Successfully submitted proposal for bounty {bounty_id}")
                    return {
                        "success": True,
                        "task_id": bounty_id,
                        "result": {
                            "submission_id": response.json().get('id'),
                            "proposal": proposal_text,
                            "status": "submitted"
                        }
                    }
                else:
                    logger.warning(f"API submission failed with status {response.status_code}")
                    # Fall back to manual submission
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"API request failed: {str(e)}")
                # Fall back to manual submission
        
        # Mark for manual submission
        logger.info(f"Marking bounty {bounty_id} for manual submission")
        return {
            "success": True,
            "task_id": bounty_id,
            "result": {
                "proposal": proposal_text,
                "submission_data": submission_data,
                "status": "manual_submission_required",
                "bounty_url": f"https://gitcoin.co/bounty/{bounty_id}",
                "instructions": "Please manually submit this proposal on the Gitcoin platform"
            }
        }
        
    except KeyError as e:
        logger.error(f"Missing required field in opportunity data: {str(e)}")
        return {"success": False, "task_id": opp.get('id'), "result": f"Missing required field: {str(e)}"}
    
    except Exception as e:
        logger.error(f"Unexpected error processing Gitcoin bounty: {str(e)}")
        return {"success": False, "task_id": opp.get('id'), "result": f"Unexpected error: {str(e)}"}