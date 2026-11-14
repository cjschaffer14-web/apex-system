"""Measured crowding features; never mapped into economics automatically."""
STATUS='research'
def crowding(events,start_ns,end_ns):
    if end_ns<=start_ns: raise ValueError('invalid observation window')
    rows=[r for r in events if start_ns<=r['timestamp_ns']<end_ns]
    seconds=(end_ns-start_ns)/1e9
    return {'observed_attempts_per_second':len(rows)/seconds,'distinct_observed_actors':len({r['actor_id'] for r in rows}),'failed_fraction':sum(bool(r['failed']) for r in rows)/len(rows) if rows else None,'selection':'observed attempts only; private/unseen activity unknown','status':STATUS}
