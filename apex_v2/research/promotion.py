"""Economic qualification records only. No order authorization, no auto-deploy."""
from dataclasses import dataclass, asdict
@dataclass(frozen=True)
class ModelCard:
    model_id: str
    target: str
    inputs: tuple
    train_window: tuple
    oos_window: tuple
    calibration: dict
    economic_increment: dict
    status: str = 'research'
    def validate(self):
        if self.status not in ('research','qualified','production'): raise ValueError('invalid status')
        if self.train_window[1]>=self.oos_window[0]: raise ValueError('overlapping train/OOS windows')
        return asdict(self)

def qualify(baseline,feature,min_episodes=100,min_increment_usd=0):
    # Require paired held-out evidence and noninferior risk/calibration/compute.
    required=('episode_ids','net_usd','brier','drawdown_usd','failure_rate','compute_seconds','capital_time_efficiency','turnover_usd','held_out')
    if any(k not in r for r in (baseline,feature) for k in required): return {'status':'research','reasons':['missing_evidence'],'orders_authorized':False}
    reasons=[]
    import math
    numeric=required[1:-1]
    if any(not isinstance(r[k],(int,float)) or not math.isfinite(r[k]) for r in (baseline,feature) for k in numeric):
        return {'status':'research','reasons':['missing_or_nonfinite_metrics'],'orders_authorized':False}
    if baseline['episode_ids']!=feature['episode_ids'] or len(set(feature['episode_ids']))<min_episodes: reasons.append('insufficient_matched_evidence')
    if not baseline['held_out'] or not feature['held_out']: reasons.append('not_held_out')
    increment=feature['net_usd']-baseline['net_usd']
    if increment<=min_increment_usd: reasons.append('no_incremental_net_value')
    for key in ('brier','drawdown_usd','failure_rate','compute_seconds','turnover_usd'):
        if feature[key]>baseline[key]: reasons.append('regressed_'+key)
    if feature['capital_time_efficiency'] is None or baseline['capital_time_efficiency'] is None or feature['capital_time_efficiency']<baseline['capital_time_efficiency']: reasons.append('regressed_capital_time')
    return {'status':'research' if reasons else 'qualified','economic_increment_usd':increment,'reasons':reasons,'orders_authorized':False,'production_requires_reviewed_code_and_new_validation':True}
