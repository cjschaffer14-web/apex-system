import json
from .episode_packet import validate_packet
FORBIDDEN=('secret','password','api_key','token','authorization','credential')
def export_packets(packets,path):
    def inspect(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if any(x in k.lower() for x in FORBIDDEN) and k.lower() not in ('start_token','token_in','token_out'): raise ValueError('sensitive field prohibited')
                inspect(v)
        elif isinstance(value,(list,tuple)):
            for v in value: inspect(v)
    rows=[]
    for p in packets: validate_packet(p); inspect(p); rows.append(json.dumps(p,allow_nan=False,sort_keys=True))
    path.write_text(''.join(r+'\n' for r in rows))
