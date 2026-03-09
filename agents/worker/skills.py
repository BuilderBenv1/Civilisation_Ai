def get_skill_confidence(skill_name):
    """Return confidence score 0-1 based on historical success"""
    confidence_map = {
        'python': 0.9,
        'javascript': 0.8,
        'data_analysis': 0.85,
        'web_scraping': 0.7,
        'api_integration': 0.75,
        'automation': 0.8
    }
    return confidence_map.get(skill_name.lower(), 0.5)

def select_best_skills(opportunity, max_skills=3):
    """Select highest confidence skills matching opportunity"""
    relevant_skills = get_relevant_skills(opportunity)
    scored_skills = [(skill, get_skill_confidence(skill)) for skill in relevant_skills]
    scored_skills.sort(key=lambda x: x[1], reverse=True)
    return [skill for skill, _ in scored_skills[:max_skills]]