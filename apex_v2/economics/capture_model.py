"""F2 conservative prior until training-only labels support calibration.
Survival is a prerequisite proxy, not proof of execution success.
"""
import math
from dataclasses import dataclass
@dataclass(frozen=True)
class CaptureModel:
    success_rate: float = .5
    observations: int = 0
    version: str = 'beta-prior-survival-v1'
    @classmethod
    def fit(cls, labels):
        labels=list(labels)
        if any(x not in (0,1,False,True) for x in labels): raise ValueError('invalid capture label')
        return cls((1+sum(labels))/(2+len(labels)),len(labels))
    def predict(self, survival, age, latency, reliability, uncertainty, crowding=0):
        if crowding!=0: raise ValueError('competition adjustment remains research until reviewed economic promotion')
        if min(age,latency,crowding)<0 or not 0<=reliability<=1 or not 0<=uncertainty<=1: raise ValueError('invalid capture inputs')
        return self.success_rate*survival.conditional(age,latency)*reliability*(1-uncertainty)*math.exp(-crowding)
