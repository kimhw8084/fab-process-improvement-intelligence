"""Non-network fake adapter implementing logical contract with deny-by-default behavior."""
class PermissionDenied(PermissionError): pass

class SyntheticFabAdapter:
    def __init__(self, approved=None):
        self.approved=set(approved or {'SYN_MEASURE','SYN_PROCESS','SYN_WAFER'})
        self.audit=[]
    def discover(self):
        return {'catalog_version':'SYNTHETIC-1','mode':'SYNTHETIC_DEMO','capabilities':['discover','semantics','relationships','read_bounded','audit']}
    def semantics(self, source_id):
        if source_id not in self.approved: raise PermissionDenied('unapproved source')
        return {'source_id':source_id,'approved':True,'version':'SYNTHETIC-1'}
    def relationships(self, src, dst):
        if src not in self.approved or dst not in self.approved: raise PermissionDenied('unknown source')
        approved = {frozenset(('SYN_PROCESS','SYN_WAFER')),frozenset(('SYN_MEASURE','SYN_WAFER'))}
        return {'approved':frozenset((src,dst)) in approved,'version':'SYNTHETIC-1','grain':'wafer_id'}
    def read_bounded(self, source_id, *, limit, rows):
        if source_id not in self.approved: raise PermissionDenied('unapproved source')
        if not isinstance(limit,int) or limit<1 or limit>1000: raise ValueError('limit 1..1000 required')
        if not isinstance(rows,list): raise TypeError('rows must be list')
        self.audit.append({'source_id':source_id,'limit':limit,'returned':min(limit,len(rows))})
        return rows[:limit]
