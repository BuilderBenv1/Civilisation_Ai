import requests
from typing import Dict, Any
import shared.config
import shared.anthropic_client

def attempt_crew3_task(opp: dict) -> dict:
    logger = shared.config.get_logger(__name__)
    
    try:
        # Extract platform-specific metadata
        task_id = opp.get('task_id', '')
        task_type = opp.get('task_type', '')
        task_description = opp.get('description', '')
        reward_amount = opp.get('reward_amount', 0)
        crypto_token = opp.get('crypto_token', '')
        requirements = opp.get('requirements', [])
        submission_url = opp.get('submission_url', '')
        api_key = shared.config.get('CREW3_API_KEY', '')
        
        if not task_id or not task_description:
            logger.error(f"Missing required task data for crew3 task: {task_id}")
            return {"success": False, "task_id": task_id, "result": "Missing required task data"}
        
        logger.info(f"Attempting crew3 task: {task_id} - {task_type}")
        
        # Draft response using Claude
        prompt = f"""
        I need to complete a micro-task on the crew3 platform. Here are the details:
        
        Task Type: {task_type}
        Description: {task_description}
        Requirements: {', '.join(requirements) if requirements else 'None specified'}
        Reward: {reward_amount} {crypto_token}
        
        Please provide a high-quality response or solution for this task. Be concise, accurate, and follow any specific requirements mentioned.
        """
        
        try:
            claude_response = shared.anthropic_client.ask(prompt)
            if not claude_response:
                logger.error(f"Failed to get Claude response for crew3 task: {task_id}")
                return {"success": False, "task_id": task_id, "result": "Failed to generate response"}
        except Exception as e:
            logger.error(f"Error getting Claude response for crew3 task {task_id}: {str(e)}")
            return {"success": False, "task_id": task_id, "result": f"Claude API error: {str(e)}"}
        
        # Prepare submission data
        submission_data = {
            "task_id": task_id,
            "response": claude_response,
            "worker_id": shared.config.get('CREW3_WORKER_ID', ''),
            "submission_type": task_type
        }
        
        # Submit via platform API if submission URL and API key available
        if submission_url and api_key:
            try:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                
                response = requests.post(
                    submission_url,
                    json=submission_data,
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code == 200:
                    result_data = response.json()
                    logger.info(f"Successfully submitted crew3 task: {task_id}")
                    return {
                        "success": True,
                        "task_id": task_id,
                        "result": {
                            "submission_id": result_data.get('submission_id'),
                            "status": result_data.get('status', 'submitted'),
                            "response": claude_response,
                            "reward_amount": reward_amount,
                            "crypto_token": crypto_token
                        }
                    }
                else:
                    logger.error(f"Failed to submit crew3 task {task_id}: HTTP {response.status_code}")
                    return {
                        "success": False,
                        "task_id": task_id,
                        "result": f"Submission failed: HTTP {response.status_code}"
                    }
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"Network error submitting crew3 task {task_id}: {str(e)}")
                # Mark for manual submission
                logger.info(f"Marking crew3 task {task_id} for manual submission")
                return {
                    "success": True,
                    "task_id": task_id,
                    "result": {
                        "status": "manual_submission_required",
                        "response": claude_response,
                        "submission_data": submission_data,
                        "error": str(e)
                    }
                }
        else:
            # Mark for manual submission if no API integration available
            logger.info(f"No API integration available for crew3 task {task_id}, marking for manual submission")
            return {
                "success": True,
                "task_id": task_id,
                "result": {
                    "status": "manual_submission_required",
                    "response": claude_response,
                    "submission_data": submission_data,
                    "reward_amount": reward_amount,
                    "crypto_token": crypto_token
                }
            }
            
    except Exception as e:
        logger.error(f"Unexpected error in crew3 task {task_id}: {str(e)}")
        return {
            "success": False,
            "task_id": task_id,
            "result": f"Unexpected error: {str(e)}"
        }