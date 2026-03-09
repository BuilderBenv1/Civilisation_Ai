def calculate_bid_amount(self, opportunity):
    base_budget = float(opportunity.budget.replace('$', '').replace(',', ''))
    # Bid 12% below budget to be competitive while maintaining profit
    competitive_bid = base_budget * 0.88
    # Ensure minimum viable bid
    min_bid = max(competitive_bid, 3.0)
    return round(min_bid, 2)