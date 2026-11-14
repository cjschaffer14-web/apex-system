STAGES=('spread_only','spread_cost','existing_observatory','episode_survival_capture','agent_inventory','competition','scientific_features')
def decisions(row):
    # Predictions must be frozen as-of decision time by each upstream model.
    # Stages do not invent omitted features or reuse a future outcome as a signal.
    out={}
    for stage in STAGES:
        p=row['predictions'].get(stage)
        out[stage]=None if p is None else bool(p['select'])
    return out

def build_predictions(features,capture_model,survival_model,asof_ns,training_end_ns):
    """Seven frozen shadow policy ablations on the same opportunity.
Features must come from decision-time data. Competition/scientific policies
are research evaluations and never imported by the production allocator.
Missing observational inputs leave a stage unavailable.
"""
    import math,time
    from ..economics.formulas import net_expected_value
    if training_end_ns>=asof_ns: raise ValueError('training must precede prediction')
    result={}; start=time.perf_counter()
    def put(stage,selected,p):
        result[stage]={'select':bool(selected),'capture_probability':p,'asof_ns':asof_ns,'training_end_ns':training_end_ns,'compute_seconds':time.perf_counter()-start,'status':'shadow_evaluation'}
    gross=features['terminal_minus_initial_usd']; cost=features['success_cost_usd']; net=gross-cost
    put('spread_only',gross>0,capture_model.success_rate)
    put('spread_cost',net>0,capture_model.success_rate)
    put('existing_observatory',features['observatory_select'],capture_model.success_rate)
    p=capture_model.predict(survival_model,features['age_seconds'],features['latency_seconds'],features['reliability'],features['uncertainty'])
    nev=net_expected_value(p,net,features['failure_loss_usd'],features['holding_cost_usd'])
    put('episode_survival_capture',nev>0,p)
    put('agent_inventory',nev>0 and features['agent_feasible'],p)
    if features.get('crowding') is not None:
        pc=p*math.exp(-features['crowding'])
        if features['crowding']<0: raise ValueError('negative crowding')
        put('competition',features['agent_feasible'] and net_expected_value(pc,net,features['failure_loss_usd'],features['holding_cost_usd'])>0,pc)
    if features.get('scientific_capture_probability') is not None:
        ps=features['scientific_capture_probability']
        put('scientific_features',features['agent_feasible'] and net_expected_value(ps,net,features['failure_loss_usd'],features['holding_cost_usd'])>0,ps)
    return result
