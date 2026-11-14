"""Kaplan-Meier opportunity survival, with right censoring and tied events."""
import math
from dataclasses import dataclass
@dataclass(frozen=True)
class SurvivalModel:
    curve: tuple
    observations: int
    version: str = 'km-v1'
    @classmethod
    def fit(cls, durations): # iterable (seconds, event_observed), training only
        rows=list(durations)
        if any(not math.isfinite(t) or t<0 for t,e in rows): raise ValueError('invalid duration')
        at_risk=len(rows); survival=1.; curve=[]
        for t in sorted({t for t,e in rows}):
            events=sum(1 for x,e in rows if x==t and e)
            censored=sum(1 for x,e in rows if x==t and not e)
            survival*=1-events/at_risk
            curve.append((t,survival)); at_risk-=events+censored
        return cls(tuple(curve),len(rows))
    def survival(self, seconds):
        if seconds<0: raise ValueError('negative horizon')
        return next((s for t,s in reversed(self.curve) if t<=seconds),1.)
    def conditional(self, age, horizon):
        denom=self.survival(age)
        return self.survival(age+horizon)/denom if denom else 0.
    @property
    def half_life(self): return next((t for t,s in self.curve if s<=.5),None)
