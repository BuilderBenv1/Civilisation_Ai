import requests
from typing import Dict, Any
import shared.config
import shared.anthropic_client

logger = shared.config.get_logger(__name__)

def attempt_dework_task(opp: dict) -> dict:
    """
    Handle Dework task opportunities
    """
    try:
        # Extract platform-specific metadata
        task_id = opp.get('id', '')
        task_title = opp.get('title', '')
        task_description = opp.get('description', '')
        bounty_amount = opp.get('bounty_amount', 0)
        token_symbol = opp.get('token_symbol', 'ETH')
        dao_name = opp.get('dao_name', '')
        skills_required = opp.get('skills_required', [])
        deadline = opp.get('deadline', '')
        task_url = opp.get('url', '')
        
        logger.info(f"Processing Dework task: {task_id} - {task_title}")
        
        # Draft response using Claude
        prompt = f"""
        I'm applying for a Web3 task on Dework platform. Please help me draft a professional proposal.
        
        Task Details:
        - Title: {task_title}
        - Description: {task_description}
        - DAO/Project: {dao_name}
        - Bounty: {bounty_amount} {token_symbol}
        - Required Skills: {', '.join(skills_required)}
        - Deadline: {deadline}
        
        Please write a concise, professional proposal that:
        1. Shows understanding of the task requirements
        2. Highlights relevant experience and skills
        3. Provides a clear approach/timeline
        4. Demonstrates knowledge of Web3/crypto space
        5. Keeps it under 300 words
        
        Format as a direct proposal message.
        """
        
        try:
            proposal_text = shared.anthropic_client.ask(prompt)
            logger.info(f"Generated proposal for task {task_id}")
        except Exception as e:
            logger.error(f"Failed to generate proposal for task {task_id}: {str(e)}")
            return {
                "success": False,
                "task_id": task_id,
                "result": f"Failed to generate proposal: {str(e)}"
            }
        
        # Prepare submission data
        submission_data = {
            "task_id": task_id,
            "proposal": proposal_text,
            "wallet_address": shared.config.get("WALLET_ADDRESS", ""),
            "estimated_hours": opp.get('estimated_hours', 8),
            "proposed_timeline": opp.get('proposed_timeline', '1 week')
        }
        
        # Check if we have API credentials for automatic submission
        api_key = shared.config.get("DEWORK_API_KEY")
        
        if api_key:
            try:
                # Submit via Dework API
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                
                api_url = f"https://api.dework.xyz/tasks/{task_id}/applications"
                
                response = requests.post(
                    api_url,
                    json=submission_data,
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code in [200, 201]:
                    logger.info(f"Successfully submitted application for task {task_id}")
                    return {
                        "success": True,
                        "task_id": task_id,
                        "result": "Application submitted successfully via API",
                        "proposal": proposal_text,
                        "application_id": response.json().get('id', '')
                    }
                else:
                    logger.error(f"API submission failed for task {task_id}: {response.status_code}")
                    # Fall back to manual submission
                    return {
                        "success": True,
                        "task_id": task_id,
                        "result": "API submission failed, marked for manual submission",
                        "proposal": proposal_text,
                        "manual_submission_required": True,
                        "task_url": task_url
                    }
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"Network error submitting to task {task_id}: {str(e)}")
                # Fall back to manual submission
                return {
                    "success": True,
                    "task_id": task_id,
                    "result": "Network error, marked for manual submission",
                    "proposal": proposal_text,
                    "manual_submission_required": True,
                    "task_url": task_url
                }
        else:
            # No API key available, mark for manual submission
            logger.info(f"No API key available, marking task {task_id} for manual submission")
            return {
                "success": True,
                "task_id": task_id,
                "result": "Marked for manual submission (no API key)",
                "proposal": proposal_text,
                "manual_submission_required": True,
                "task_url": task_url,
                "submission_instructions": f"Apply at: {task_url}"
            }
            
    except KeyError as e:
        logger.error(f"Missing required field in opportunity data: {str(e)}")
        return {
            "success": False,
            "task_id": opp.get('id', 'unknown'),
            "result": f"Missing required field: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Unexpected error processing Dework task: {str(e)}")
        return {
            "success": False,
            "task_id": opp.get('id', 'unknown'),
            "result": f"Unexpected error: {str(e)}"
        }