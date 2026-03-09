def filter_by_budget(opportunities):
    """Filter opportunities by minimum budget threshold"""
    filtered = []
    for opp in opportunities:
        budget = extract_budget(opp.get('description', ''))
        if budget >= 50:  # Minimum $50 threshold
            opp['estimated_budget'] = budget
            filtered.append(opp)
    return filtered

def extract_budget(description):
    """Extract budget from opportunity description"""
    import re
    patterns = [r'\$([0-9,]+)', r'budget:?\s*([0-9,]+)', r'pay:?\s*\$?([0-9,]+)']
    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            return int(match.group(1).replace(',', ''))
    return 25  # Default estimate