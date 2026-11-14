def calibration(predicted,labels,bins=10):
    rows=list(zip(predicted,labels))
    if len(predicted)!=len(labels) or any(not 0<=p<=1 or y not in (0,1) for p,y in rows): raise ValueError('invalid calibration evidence')
    if not rows: return {'brier':None,'bins':[],'n':0}
    report=[]
    for i in range(bins):
        bucket=[(p,y) for p,y in rows if min(bins-1,int(p*bins))==i]
        if bucket: report.append({'bin':i,'n':len(bucket),'predicted':sum(p for p,y in bucket)/len(bucket),'observed':sum(y for p,y in bucket)/len(bucket)})
    return {'brier':sum((p-y)**2 for p,y in rows)/len(rows),'bins':report,'n':len(rows)}
