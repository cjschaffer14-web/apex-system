def violations(c, state):
    c.validate()
    reasons=[]
    if not state.operational or not state.legal_allowed: reasons.append('legal_or_operational')
    if state.latency_seconds>state.max_latency_seconds: reasons.append('latency')
    if not c.quality_ok or not c.liquidity_ok or not c.settlement_ok: reasons.append('measurement_liquidity_settlement')
    if c.feature_status!='production': reasons.append('unpromoted_feature')
    if c.capital_usd>state.capital_usd: reasons.append('capital')
    if c.margin_usd>state.margin_usd: reasons.append('margin')
    for k,v in c.inventory_required.items():
        if v>state.inventory.get(k,0): reasons.append('inventory:'+k)
    for k,v in c.venue_usage.items():
        if k not in state.available_venues or k not in state.venue_limits or v>state.venue_limits[k]: reasons.append('venue:'+k)
    return reasons
