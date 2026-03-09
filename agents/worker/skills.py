def get_skill_confidence(self, required_skills):
    our_skills = ['writing', 'research', 'data_analysis', 'social_media', 'basic_coding']
    skill_weights = {'writing': 0.9, 'research': 0.8, 'data_analysis': 0.7, 'social_media': 0.8, 'basic_coding': 0.6}
    
    confidence = 0
    for skill in required_skills:
        if skill.lower() in our_skills:
            confidence += skill_weights.get(skill.lower(), 0.5)
    
    return min(confidence / len(required_skills), 1.0) if required_skills else 0.5

def should_bid(self, opportunity):
    confidence = self.get_skill_confidence(opportunity.required_skills)
    return confidence >= 0.7  # Only bid if we're 70%+ confident