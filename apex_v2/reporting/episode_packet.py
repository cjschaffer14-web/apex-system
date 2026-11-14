import json
from ..economics.formulas import FORMULAS
SCHEMA_VERSION='1.0.0'
FIELDS=('schema_version','episode_id','timestamp_ns','market','mechanism','economic_venues','observations','opportunity','agent_state','prediction','decision','realized_shadow_outcome','attribution','provenance','censoring','selection')
def validate_packet(p):
    if any(k not in p for k in FIELDS): raise ValueError('missing packet fields')
    if p['schema_version']!=SCHEMA_VERSION: raise ValueError('unknown schema')
    if p['decision'].get('mode') not in ('shadow','paper') or p['decision'].get('orders_authorized') is not False: raise ValueError('unsafe decision')
    if p['provenance'].get('formula_ids')!=list(FORMULAS): raise ValueError('formula provenance required')
    if not p['provenance'].get('code_commit') or not p['provenance'].get('model_versions') or not p['provenance'].get('source_ids'): raise ValueError('missing provenance')
    json.dumps(p,allow_nan=False)
    return p
