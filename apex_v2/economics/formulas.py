"""Stable F1-F5. USD and seconds unless explicitly declared otherwise."""
import math
FORMULAS = {'F1':'G=V_T-V_0-C', 'F2':'p=P(capture|S,W,j)', 'F3':'NEV=p*G-(1-p)*L-H', 'F4':'argmax(sum(NEV)-lambda*R) subject to feasibility', 'F5':'eta=net_capture/(capital*time_at_risk_seconds)'}
def finite(*xs):
    if not all(math.isfinite(x) for x in xs): raise ValueError('nonfinite economic input')
def gross_value(terminal, initial, costs):
    finite(terminal,initial,costs)
    if costs<0: raise ValueError('negative cost')
    return terminal-initial-costs
def net_expected_value(p, gross, failure_loss, holding_cost):
    finite(p,gross,failure_loss,holding_cost)
    if not 0<=p<=1 or min(failure_loss,holding_cost)<0: raise ValueError('invalid probability or loss')
    return p*gross-(1-p)*failure_loss-holding_cost
def capital_time_efficiency(net, capital, seconds):
    finite(net,capital,seconds)
    if capital<=0 or seconds<=0: return None
    return net/(capital*seconds)
