def calculate_competitive_price(opportunity_budget, complexity_score):
    """Calculate competitive price based on budget and complexity"""
    if opportunity_budget <= 100:
        # For small budgets, bid 60-70% to win
        return int(opportunity_budget * 0.65)
    elif opportunity_budget <= 500:
        # Medium budgets, bid 70-80%
        return int(opportunity_budget * 0.75)
    else:
        # Large budgets, can bid higher percentage
        return int(opportunity_budget * 0.85)

def generate_proposal_price(opportunity):
    """Generate competitive proposal price"""
    budget = opportunity.get('estimated_budget', 100)
    complexity = estimate_complexity(opportunity.get('description', ''))
    base_price = calculate_competitive_price(budget, complexity)
    # Add small random factor to avoid identical bids
    import random
    return max(25, base_price + random.randint(-5, 5))