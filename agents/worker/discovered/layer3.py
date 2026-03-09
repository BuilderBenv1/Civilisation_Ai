import requests
from typing import Dict, Any
import shared.config
import shared.anthropic_client

def attempt_layer3_task(opp: dict) -> dict:
    logger = shared.config.get_logger(__name__)
    
    try:
        # Extract platform-specific metadata
        task_id = opp.get('id', '')
        title = opp.get('title', '')
        description = opp.get('description', '')
        requirements = opp.get('requirements', [])
        reward = opp.get('reward', {})
        deadline = opp.get('deadline', '')
        task_type = opp.get('task_type', '')
        project_info = opp.get('project_info', {})
        
        logger.info(f"Attempting Layer3 task: {task_id} - {title}")
        
        # Draft response using Claude
        prompt = f"""
        I need to complete a Web3/crypto bounty task on Layer3 platform.
        
        Task: {title}
        Description: {description}
        Requirements: {', '.join(requirements) if requirements else 'None specified'}
        Task Type: {task_type}
        Reward: {reward.get('amount', 'Not specified')} {reward.get('token', '')}
        Deadline: {deadline}
        Project Info: {project_info}
        
        Please provide a detailed proposal/response for completing this task. Include:
        1. Understanding of the requirements
        2. Approach to complete the task
        3. Timeline and deliverables
        4. Any questions or clarifications needed
        
        Keep the response professional and demonstrate expertise in Web3/crypto space.
        """
        
        response = shared.anthropic_client.ask(prompt)
        
        if not response:
            logger.error(f"Failed to generate response for Layer3 task {task_id}")
            return {"success": False, "task_id": task_id, "result": "Failed to generate response"}
        
        # Prepare submission data
        submission_data = {
            "task_id": task_id,
            "proposal": response,
            "estimated_completion": deadline,
            "worker_profile": {
                "skills": ["Web3", "Blockchain", "Smart Contracts", "DeFi"],
                "experience": "Experienced in crypto and Web3 development"
            }
        }
        
        # Check if we have API credentials for automated submission
        api_key = shared.config.get('LAYER3_API_KEY')
        api_url = shared.config.get('LAYER3_API_URL', 'https://api.layer3.xyz')
        
        if api_key:
            try:
                headers = {
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                }
                
                submit_response = requests.post(
                    f"{api_url}/tasks/{task_id}/apply",
                    json=submission_data,
                    headers=headers,
                    timeout=30
                )
                
                if submit_response.status_code == 200:
                    result_data = submit_response.json()
                    logger.info(f"Successfully submitted Layer3 task {task_id}")
                    return {
                        "success": True,
                        "task_id": task_id,
                        "result": {
                            "submission_id": result_data.get('submission_id'),
                            "status": "submitted",
                            "proposal": response,
                            "platform_response": result_data
                        }
                    }
                else:
                    logger.warning(f"API submission failed for Layer3 task {task_id}: {submit_response.status_code}")
                    # Fall through to manual submission
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"API request failed for Layer3 task {task_id}: {str(e)}")
                # Fall through to manual submission
        
        # Mark for manual submission
        logger.info(f"Marking Layer3 task {task_id} for manual submission")
        return {
            "success": True,
            "task_id": task_id,
            "result": {
                "status": "manual_submission_required",
                "proposal": response,
                "submission_data": submission_data,
                "platform": "layer3",
                "task_url": opp.get('url', ''),
                "instructions": "Please manually submit this proposal on the Layer3 platform"
            }
        }
        
    except Exception as e:
        logger.error(f"Error processing Layer3 task {task_id}: {str(e)}")
        return {
            "success": False,
            "task_id": task_id,
            "result": f"Error processing task: {str(e)}"
        }