def assess_skill_match(self, opportunity_description):
    skill_keywords = {
        'python': ['python', 'script', 'automation', 'api'],
        'data_analysis': ['data', 'analysis', 'csv', 'excel'],
        'web_scraping': ['scraping', 'web data', 'extract'],
        'content': ['writing', 'content', 'blog', 'article']
    }
    
    confidence = 0
    desc_lower = opportunity_description.lower()
    
    for skill, keywords in skill_keywords.items():
        if any(kw in desc_lower for kw in keywords):
            confidence += 0.25
    
    return confidence >= 0.5  # Only bid if we're confident