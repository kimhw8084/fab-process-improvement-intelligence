"""Deterministic synthetic catalog. This is NEVER a real Fab Insight MCP."""
import random

def synthetic_catalog(n=13000, seed=20261122):
    if not 1 <= n <= 100000:
        raise ValueError('n must be 1..100000')
    rng=random.Random(seed)
    areas=('MET','PHOTO','ETCH','DEP','DIFF','IMPL','CMP','WAT','SORT')
    out=[]
    for i in range(n):
        area=areas[i % len(areas)]
        columns=['wafer_id','lot_id','step_instance_id','event_ts','measure_value']
        if i % 13 == 0: columns.append('equipment_id')
        if i % 17 == 0: columns.append('chamber_id')
        out.append({'id':f'SYN_{area}_{i:05d}','area':area,'columns':columns,
             'approved':i % 11 != 0,'relationship_group':f'GRP_{i % 31:02d}',
             'timestamp_timezone':rng.choice(['UTC','local_unknown']),
             'source':'SYNTHETIC_ONLY'})
    return out

def approved_join(table_a, table_b, key, catalog):
    index={t['id']:t for t in catalog}
    a=index.get(table_a); b=index.get(table_b)
    return bool(a and b and a['approved'] and b['approved']
                and a['relationship_group']==b['relationship_group']
                and key in a['columns'] and key in b['columns']
                and key=='step_instance_id')
