def evaluate_opportunity(self, opp):
    # Existing evaluation logic...
    
    # Add budget efficiency filter
    estimated_hours = self.estimate_effort(opp.get('description', ''))
    budget = float(opp.get('budget', 0))
    hourly_rate = budget / max(estimated_hours, 0.5)  # Avoid division by zero
    
    if hourly_rate < 15:  # Minimum viable rate
        return {'viable': False, 'reason': 'insufficient_budget_ratio'}
    
    # Continue with existing evaluation...