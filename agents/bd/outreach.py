def prioritize_outreach_targets(opportunities):
    # Focus 80% of effort on Twitter since it's 87% of opportunities
    twitter_opps = [opp for opp in opportunities if opp.get('platform') == 'twitter']
    other_opps = [opp for opp in opportunities if opp.get('platform') != 'twitter']
    
    # Sort Twitter opportunities by engagement/followers for better targeting
    twitter_opps.sort(key=lambda x: x.get('engagement_score', 0), reverse=True)
    
    # Return prioritized list: top Twitter opportunities first
    return twitter_opps[:20] + other_opps[:5]  # Focus on top Twitter targets