def utilization(required,available):
    if any(v<0 for v in required.values()) or any(v<0 for v in available.values()): raise ValueError('negative inventory')
    return {k:(v/available[k] if available.get(k,0)>0 else None) for k,v in required.items()}
