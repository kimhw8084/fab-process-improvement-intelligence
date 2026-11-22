"""One-way manifest compatibility gate. A passing check does NOT equal suite qualification."""
import json, sys, hashlib
from pathlib import Path

def inspect(*dirs):
    products=[]; routes=[]; contracts=[]
    for d in dirs:
        base=Path(d)
        p=json.loads((base/'product.json').read_text())
        products.append(p['product_id'])
        routes.append(p['entrypoints']['ui_route'])
        contracts.append(hashlib.sha256((base/'contracts'/'evidence.v1.schema.json').read_bytes()).hexdigest())
        if p['contract_version']!='1.0.0': raise ValueError('version mismatch')
        if p['release_state']!='EXTERNAL_TRANSFER_READY': raise ValueError('product is not independently released: '+p['product_id'])
    if len(products)!=len(set(products)) or len(routes)!=len(set(routes)) or len(contracts)!=1:
        raise ValueError('duplicate product/route or incompatible evidence contracts')
    if set(products)!={'p1','p2','p3','p4'}: raise ValueError('all four verified release products required')
    return {'status':'MANIFEST_COMPATIBLE_ONLY','products':sorted(products),
            'next':'Execute actual offline dependency, security, UI, scientific cross-product, auth and OS integration tests; manifest check is NOT full suite success.'}
if __name__=='__main__':
    try: print(json.dumps(inspect(*sys.argv[1:]),indent=2))
    except Exception as e: print('NOT READY:',str(e),file=sys.stderr);sys.exit(1)
