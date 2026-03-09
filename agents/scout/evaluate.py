def should_evaluate_opportunity(self, opp):
    # Skip opportunities with budget < $5 to focus on profitable work
    if hasattr(opp, 'budget') and opp.budget and float(opp.budget.replace('$', '').replace(',', '')) < 5.0:
        return False
    # Skip opportunities with suspicious keywords indicating spec work
    spam_keywords = ['test', 'sample', 'free', 'trial', 'exposure']
    if any(keyword in opp.title.lower() for keyword in spam_keywords):
        return False
    return True