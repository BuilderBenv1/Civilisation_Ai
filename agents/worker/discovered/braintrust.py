import requests
from typing import Dict, Any
from shared import config, anthropic_client

def attempt_braintrust_task(opp: dict) -> dict:
    logger = config.get_logger(__name__)
    
    try:
        # Extract platform-specific metadata
        task_id = opp.get('id', '')
        title = opp.get('title', '')
        description = opp.get('description', '')
        budget = opp.get('budget', {})
        skills_required = opp.get('skills', [])
        client_address = opp.get('client_wallet', '')
        deadline = opp.get('deadline', '')
        
        logger.info(f"Processing Braintrust task: {task_id}")
        
        # Draft proposal using Claude
        prompt = f"""
        Draft a professional proposal for this freelance task on Braintrust:
        
        Title: {title}
        Description: {description}
        Budget: {budget}
        Required Skills: {', '.join(skills_required)}
        Deadline: {deadline}
        
        Write a compelling proposal that:
        1. Demonstrates understanding of the requirements
        2. Highlights relevant experience and skills
        3. Provides a clear timeline and deliverables
        4. Shows enthusiasm for crypto/blockchain projects
        5. Keeps it concise but thorough
        
        Format as a professional proposal ready to submit.
        """
        
        proposal_text = anthropic_client.ask(prompt)
        
        if not proposal_text:
            logger.error(f"Failed to generate proposal for task {task_id}")
            return {"success": False, "task_id": task_id, "result": "Failed to generate proposal"}
        
        # Prepare submission data
        submission_data = {
            "task_id": task_id,
            "proposal": proposal_text,
            "bid_amount": budget.get('max', 0) * 0.9,  # Bid 10% below max budget
            "estimated_hours": opp.get('estimated_hours', 40),
            "delivery_time": deadline
        }
        
        # Submit via Braintrust API
        api_key = config.get('BRAINTRUST_API_KEY')
        if not api_key:
            logger.warning(f"No Braintrust API key found, marking task {task_id} for manual submission")
            return {
                "success": True,
                "task_id": task_id,
                "result": "marked_for_manual_submission",
                "proposal": proposal_text,
                "submission_data": submission_data
            }
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            f"https://api.braintrust.com/v1/tasks/{task_id}/proposals",
            json=submission_data,
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 201:
            result_data = response.json()
            logger.info(f"Successfully submitted proposal for Braintrust task {task_id}")
            return {
                "success": True,
                "task_id": task_id,
                "result": "submitted",
                "proposal_id": result_data.get('proposal_id'),
                "submission_data": submission_data
            }
        else:
            logger.error(f"Failed to submit Braintrust proposal: {response.status_code} - {response.text}")
            return {
                "success": False,
                "task_id": task_id,
                "result": f"API error: {response.status_code}",
                "proposal": proposal_text
            }
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error submitting Braintrust task {task_id}: {str(e)}")
        return {"success": False, "task_id": task_id, "result": f"Network error: {str(e)}"}
    
    except Exception as e:
        logger.error(f"Unexpected error processing Braintrust task {task_id}: {str(e)}")
        return {"success": False, "task_id": task_id, "result": f"Error: {str(e)}"}