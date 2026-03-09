import requests
from typing import Dict, Any
import shared.config
import shared.anthropic_client

logger = shared.config.get_logger(__name__)

def attempt_wonderverse_task(opp: dict) -> dict:
    """
    Handle tasks from Wonderverse DAO task marketplace
    """
    try:
        # Extract platform-specific metadata
        task_id = opp.get('id', '')
        title = opp.get('title', '')
        description = opp.get('description', '')
        bounty_amount = opp.get('bounty_amount', 0)
        crypto_token = opp.get('crypto_token', 'ETH')
        dao_name = opp.get('dao_name', '')
        requirements = opp.get('requirements', [])
        deadline = opp.get('deadline', '')
        skills_needed = opp.get('skills_needed', [])
        
        logger.info(f"Processing Wonderverse task: {task_id} - {title}")
        
        # Prepare context for Claude
        context = f"""
        Task: {title}
        Description: {description}
        DAO: {dao_name}
        Bounty: {bounty_amount} {crypto_token}
        Deadline: {deadline}
        Required Skills: {', '.join(skills_needed)}
        Requirements: {', '.join(requirements)}
        """
        
        # Draft proposal using Claude
        prompt = f"""
        I need to write a proposal for a DAO task on Wonderverse marketplace. Here are the details:
        
        {context}
        
        Please write a professional proposal that:
        1. Shows understanding of the task requirements
        2. Highlights relevant experience and skills
        3. Provides a clear approach/methodology
        4. Demonstrates value for the DAO
        5. Is concise but comprehensive
        6. Mentions crypto/Web3 experience if relevant
        
        Keep it under 500 words and make it compelling for DAO members to vote on.
        """
        
        proposal_text = shared.anthropic_client.ask(prompt)
        
        if not proposal_text:
            logger.error(f"Failed to generate proposal for task {task_id}")
            return {
                "success": False,
                "task_id": task_id,
                "result": "Failed to generate proposal"
            }
        
        # Prepare submission data
        submission_data = {
            "task_id": task_id,
            "proposal": proposal_text,
            "estimated_completion_time": opp.get('estimated_hours', 40),
            "wallet_address": shared.config.get('CRYPTO_WALLET_ADDRESS', ''),
            "portfolio_links": shared.config.get('PORTFOLIO_LINKS', [])
        }
        
        # Check if we have API credentials for automatic submission
        api_key = shared.config.get('WONDERVERSE_API_KEY')
        api_url = shared.config.get('WONDERVERSE_API_URL', 'https://api.wonderverse.xyz')
        
        if api_key:
            try:
                # Submit proposal via API
                headers = {
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                }
                
                response = requests.post(
                    f"{api_url}/tasks/{task_id}/proposals",
                    json=submission_data,
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code == 201:
                    result_data = response.json()
                    proposal_id = result_data.get('proposal_id', '')
                    
                    logger.info(f"Successfully submitted proposal {proposal_id} for task {task_id}")
                    
                    return {
                        "success": True,
                        "task_id": task_id,
                        "result": {
                            "proposal_id": proposal_id,
                            "status": "submitted",
                            "proposal_text": proposal_text,
                            "bounty_amount": bounty_amount,
                            "crypto_token": crypto_token,
                            "submission_method": "api"
                        }
                    }
                else:
                    logger.warning(f"API submission failed with status {response.status_code}: {response.text}")
                    # Fall through to manual submission
                    
            except requests.exceptions.RequestException as e:
                logger.warning(f"API request failed: {str(e)}, falling back to manual submission")
                # Fall through to manual submission
        
        # Mark for manual submission
        logger.info(f"Marking task {task_id} for manual submission")
        
        return {
            "success": True,
            "task_id": task_id,
            "result": {
                "status": "manual_submission_required",
                "proposal_text": proposal_text,
                "platform_url": f"https://wonderverse.xyz/tasks/{task_id}",
                "bounty_amount": bounty_amount,
                "crypto_token": crypto_token,
                "dao_name": dao_name,
                "submission_method": "manual",
                "instructions": "Please manually submit this proposal on the Wonderverse platform"
            }
        }
        
    except Exception as e:
        logger.error(f"Error processing Wonderverse task {opp.get('id', 'unknown')}: {str(e)}")
        return {
            "success": False,
            "task_id": opp.get('id', ''),
            "result": f"Error processing task: {str(e)}"
        }