import requests
from typing import Dict, Any
import shared.config
import shared.anthropic_client

def attempt_coordinape_task(opp: dict) -> dict:
    logger = shared.config.get_logger(__name__)
    
    try:
        # Extract platform-specific metadata
        task_id = opp.get('id', '')
        title = opp.get('title', '')
        description = opp.get('description', '')
        reward_amount = opp.get('reward_amount', 0)
        reward_token = opp.get('reward_token', 'ETH')
        circle_id = opp.get('circle_id', '')
        deadline = opp.get('deadline', '')
        requirements = opp.get('requirements', [])
        
        logger.info(f"Attempting Coordinape task: {task_id} - {title}")
        
        # Draft response using Claude
        prompt = f"""
        I need to submit a proposal for a task on Coordinape, a decentralized compensation platform.
        
        Task Details:
        - Title: {title}
        - Description: {description}
        - Reward: {reward_amount} {reward_token}
        - Circle ID: {circle_id}
        - Deadline: {deadline}
        - Requirements: {', '.join(requirements) if requirements else 'None specified'}
        
        Please draft a professional proposal that:
        1. Demonstrates understanding of the task requirements
        2. Outlines my approach and methodology
        3. Highlights relevant experience and skills
        4. Provides a realistic timeline
        5. Shows enthusiasm for contributing to the circle
        
        Keep it concise but compelling, suitable for a crypto/DeFi community.
        """
        
        proposal = shared.anthropic_client.ask(prompt)
        
        if not proposal:
            logger.error(f"Failed to generate proposal for task {task_id}")
            return {"success": False, "task_id": task_id, "result": "Failed to generate proposal"}
        
        # Prepare submission data
        submission_data = {
            "circle_id": circle_id,
            "task_id": task_id,
            "proposal": proposal,
            "estimated_hours": opp.get('estimated_hours', 8),
            "wallet_address": shared.config.get('CRYPTO_WALLET_ADDRESS', ''),
        }
        
        # Check if we have API credentials for automatic submission
        api_key = shared.config.get('COORDINAPE_API_KEY')
        base_url = shared.config.get('COORDINAPE_API_URL', 'https://api.coordinape.com/v1')
        
        if api_key:
            # Attempt automatic submission
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                f"{base_url}/tasks/{task_id}/proposals",
                json=submission_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 201:
                result_data = response.json()
                logger.info(f"Successfully submitted proposal for Coordinape task {task_id}")
                return {
                    "success": True,
                    "task_id": task_id,
                    "result": {
                        "proposal_id": result_data.get('id'),
                        "status": "submitted",
                        "proposal": proposal,
                        "submission_method": "automatic"
                    }
                }
            else:
                logger.warning(f"API submission failed for task {task_id}: {response.status_code}")
                # Fall through to manual submission
        
        # Mark for manual submission
        logger.info(f"Marking Coordinape task {task_id} for manual submission")
        return {
            "success": True,
            "task_id": task_id,
            "result": {
                "status": "pending_manual_submission",
                "proposal": proposal,
                "submission_data": submission_data,
                "submission_method": "manual",
                "platform_url": f"https://app.coordinape.com/circles/{circle_id}/tasks/{task_id}"
            }
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error while processing Coordinape task {task_id}: {str(e)}")
        return {"success": False, "task_id": task_id, "result": f"Network error: {str(e)}"}
    
    except KeyError as e:
        logger.error(f"Missing required field for Coordinape task {task_id}: {str(e)}")
        return {"success": False, "task_id": task_id, "result": f"Missing required field: {str(e)}"}
    
    except Exception as e:
        logger.error(f"Unexpected error processing Coordinape task {task_id}: {str(e)}")
        return {"success": False, "task_id": task_id, "result": f"Unexpected error: {str(e)}"}