from dataclasses import dataclass
from .observations import ShadowPriceEngine
@dataclass(frozen=True)
class StateEstimate:
    shadow_price: object
    uncertainty: float
    freshness_seconds: dict
    references: tuple
    source_status: dict

def aggregate_source_status(status_by_asset):
    sources={s for statuses in status_by_asset.values() for s in statuses}
    return {s:{'status':('reachable' if all(v=='reachable' for v in vals) else 'blocked' if all(v!='reachable' for v in vals) else 'partial'),'by_asset':{a:rows.get(s,'missing') for a,rows in status_by_asset.items()}} for s in sources for vals in [[rows.get(s,'missing') for rows in status_by_asset.values()]]}
def estimate(asset, observations, now_ns, max_age_s=2):
    shadow=ShadowPriceEngine(max_age_s=max_age_s).build(asset,observations,now_ns)
    fresh={o.source_id:(now_ns-o.ts_ns)/1e9 for o in observations if o.asset==asset}
    return StateEstimate(shadow,1-shadow.confidence,fresh,tuple(o.source_id for o in observations if not o.executable),{})
