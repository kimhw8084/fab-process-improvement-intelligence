"""Frozen P1-P4 shared evidence contract; no remote dependencies."""
from __future__ import annotations
import hashlib, json
from typing import Any

CONTRACT_VERSION='1.0.0'
PRODUCT_IDS=frozenset({'p1','p2','p3','p4'})
MODES=frozenset({'SYNTHETIC_DEMO','INTERNAL_AUTHORIZED'})
STATUSES=frozenset({'VALID','PARTIAL','INCONCLUSIVE','REFUSED','ERROR'})
CATEGORIES=frozenset({'DESCRIPTIVE','ASSOCIATION','PREDICTION','CAUSAL_ESTIMATE','INTERVENTION_VALIDATED'})

class ContractError(ValueError): pass

def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

def envelope(product_id, raw_input, status, claims, limitations=(), *, mode='SYNTHETIC_DEMO', assumptions=(), sources=None):
    if product_id not in PRODUCT_IDS: raise ContractError('unknown product')
    if mode not in MODES: raise ContractError('invalid mode')
    if status not in STATUSES: raise ContractError('invalid status')
    if mode=='INTERNAL_AUTHORIZED': raise ContractError('bootstrap is never an authorized internal connector')
    input_hash=digest(raw_input)
    ev={'schema_version':CONTRACT_VERSION,'investigation_id':f'SYN-{product_id}-{input_hash[:12]}',
        'product_id':product_id,'mode':mode,'status':status,'claims':list(claims),'sources':sources or [],
        'assumptions':list(assumptions),'limitations':list(limitations),
        'provenance':{'engine_version':'1.0.0','input_sha256':input_hash,'semantic_catalog_version':'SYNTHETIC-1'}}
    validate_envelope(ev)
    return ev

def authorized_envelope(product_id, raw_input, status, claims, limitations=(), *, assumptions=(), sources=None,
                        authorization_reference):
    """Build an envelope only after the site-owned acquisition path qualifies.

    This helper records caller-supplied authorization provenance; it does not
    authenticate the company approval or replace site-side qualification.
    """
    if product_id not in PRODUCT_IDS or status not in STATUSES:
        raise ContractError('unknown product or status')
    if not isinstance(authorization_reference, str) or not authorization_reference.strip():
        raise ContractError('internal evidence requires an explicit site authorization reference')
    input_hash = digest(raw_input)
    ev = {'schema_version': CONTRACT_VERSION, 'investigation_id': f'P4-{input_hash[:12]}',
          'product_id': product_id, 'mode': 'INTERNAL_AUTHORIZED', 'status': status,
          'claims': list(claims), 'sources': sources or [], 'assumptions': list(assumptions),
          'limitations': list(limitations),
          'provenance': {'engine_version': '1.0.0', 'input_sha256': input_hash,
                         'authorization_reference': authorization_reference}}
    validate_envelope(ev)
    return ev

def validate_envelope(ev):
    allowed={'schema_version','investigation_id','product_id','mode','status','claim_category','claims','sources',
             'populations','transformations','units','assumptions','counterevidence','limitations','uncertainty','artifacts','provenance'}
    if not isinstance(ev,dict) or set(ev)-allowed:
        raise ContractError('evidence envelope has invalid top-level properties')
    for key in ('schema_version','investigation_id','product_id','mode','status','claims','sources','assumptions','limitations','provenance'):
        if key not in ev: raise ContractError('missing '+key)
    if ev['schema_version'] != CONTRACT_VERSION or ev['product_id'] not in PRODUCT_IDS or ev['mode'] not in MODES or ev['status'] not in STATUSES:
        raise ContractError('bad enumerated field')
    if ev['mode']=='SYNTHETIC_DEMO' and ev['investigation_id'][:4]!='SYN-': raise ContractError('synthetic case not labeled')
    if not all(isinstance(ev[k],list) for k in ('claims','sources','assumptions','limitations')): raise ContractError('claims, sources, assumptions and limitations must be lists')
    provenance=ev['provenance']
    if not isinstance(provenance,dict) or not all(isinstance(provenance.get(k),str) and provenance[k] for k in ('engine_version','input_sha256')):
        raise ContractError('incomplete provenance')
    if len(provenance['input_sha256']) != 64 or any(c not in '0123456789abcdef' for c in provenance['input_sha256'].lower()):
        raise ContractError('input_sha256 must be a SHA-256 hex digest')
    if ev['mode']=='INTERNAL_AUTHORIZED' and (not isinstance(provenance.get('authorization_reference'), str)
            or not provenance['authorization_reference'].strip()):
        raise ContractError('internal evidence requires an explicit site authorization reference')
    for claim in ev['claims']:
        if not isinstance(claim,dict) or set(claim)-{'statement','category','source_ids','method','certainty'}: raise ContractError('invalid claim object')
        for field in ('statement','category','source_ids','method','certainty'):
            if field not in claim: raise ContractError('incomplete claim')
        if not isinstance(claim['statement'],str) or not isinstance(claim['method'],str) or not isinstance(claim['source_ids'],list) or not all(isinstance(x,str) for x in claim['source_ids']):
            raise ContractError('invalid claim value type')
        if not isinstance(claim['category'],str) or claim['category'] not in CATEGORIES: raise ContractError('invalid claim category')
        if claim['certainty'] not in ('SUPPORTED','CONDITIONAL','INCONCLUSIVE'): raise ContractError('invalid certainty')
    source_allowed={'id','approved_semantic_version','grain','source_hash','permissions_ref','observed_at'}
    for source in ev['sources']:
        if not isinstance(source,dict) or set(source)-source_allowed: raise ContractError('invalid source object')
        for key in ('id','approved_semantic_version','grain','source_hash'):
            if not isinstance(source.get(key),str) or not source[key]: raise ContractError('incomplete source reference')
        if ev['mode']=='SYNTHETIC_DEMO' and not source['id'].startswith('SYN-'): raise ContractError('synthetic source is not labeled')
        if ev['mode']=='INTERNAL_AUTHORIZED' and (not isinstance(source.get('permissions_ref'), str)
                or not source['permissions_ref'].strip()): raise ContractError('internal source has no permission reference')
    if ev['status'] in ('INCONCLUSIVE','REFUSED') and not ev['limitations']:
        raise ContractError('an inconclusive/refused result requires a reason')
    return True

def claim(statement,category='DESCRIPTIVE',method='deterministic_baseline',source_ids=None,certainty='SUPPORTED'):
    return {'statement':statement,'category':category,'source_ids':source_ids or [],'method':method,'certainty':certainty}
