"""Two-venue proposal preserved as a baseline, never called a global optimizer."""
from ..observatory.observations import PortfolioStateRebalancer

def compare_matched(chasing,rebalancing):
    if set(chasing)!=set(rebalancing): raise ValueError('same episode IDs required, including no-action episodes')
    metrics=('net_usd','turnover_usd','movement_cost_usd','capital_seconds','inventory_utilization','failure_proxy','risk_proxy')
    result={'episodes':sorted(chasing),'scope':'matched supplied policies; no assumed winner','metrics':{}}
    for m in metrics:
        a=sum(chasing[k][m] for k in chasing); b=sum(rebalancing[k][m] for k in chasing)
        if m=='inventory_utilization' and chasing: a/=len(chasing); b/=len(chasing)
        result['metrics'][m]={'opportunity_chasing':a,'inventory_rebalancing':b,'delta':b-a}
    return result


def value_open_transition(initial_inventory,terminal_inventory,declared_prices,valuation_id):
    """Open portfolio valuation is a declared benchmark, not reference-free alpha."""
    if not valuation_id: raise ValueError('declared valuation ID required')
    assets=set(initial_inventory)|set(terminal_inventory)
    if not assets<=declared_prices.keys(): raise ValueError('missing declared price')
    from ..economics.formulas import finite
    finite(*declared_prices.values(),*initial_inventory.values(),*terminal_inventory.values())
    if any(declared_prices[k]<=0 for k in assets): raise ValueError('invalid declared valuation')
    return {'valuation_id':valuation_id,'accounting':'declared_open_portfolio','terminal_minus_initial_usd':sum((terminal_inventory.get(k,0)-initial_inventory.get(k,0))*declared_prices[k] for k in assets)}
