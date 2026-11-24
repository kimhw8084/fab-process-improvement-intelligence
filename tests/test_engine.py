import copy, json, unittest
from pathlib import Path
from fabintel.project import analyze
from fabintel.contracts import validate_envelope
BASE=Path(__file__).resolve().parent.parent
class EngineCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.positive=json.loads((BASE/'fixtures'/'case_positive.json').read_text())
        cls.negative=json.loads((BASE/'fixtures'/'case_negative.json').read_text())
        cls.oracle=json.loads((BASE/'fixtures'/'independent_oracle.json').read_text())
    def test_fixed_positive_oracle(self):
        result=analyze(self.positive); validate_envelope(result)
        self.assertEqual(result['status'],self.oracle['positive_status'])
        self.assertTrue(any(self.oracle['claim_contains'] in c['statement'] for c in result['claims']))
        self.assertEqual(result['mode'],'SYNTHETIC_DEMO')
    def test_fixed_negative_oracle(self):
        result=analyze(self.negative)
        self.assertEqual(result['status'],self.oracle['negative_status'])
        self.assertEqual(result['claims'],[])
        self.assertTrue(result['limitations'])
    def test_deterministic(self):
        self.assertEqual(analyze(self.positive),analyze(self.positive))
    def test_never_claim_caused_or_control(self):
        result=analyze(self.positive)
        self.assertTrue(all(c['category'] not in ('CAUSAL_ESTIMATE','INTERVENTION_VALIDATED') for c in result['claims']))
    def test_internal_mode_requires_a_matching_qualified_mcp_audit_receipt(self):
        data=copy.deepcopy(json.loads((BASE/'fixtures'/'full_workflow_demo.json').read_text()))
        source_hash='a'*64
        data['mode']='INTERNAL_AUTHORIZED'
        data['sources']=[{'id':'ETCH-OBSERVATIONS','approved_semantic_version':'SEM-7',
            'grain':data['grain'],'source_hash':source_hash,'permissions_ref':'SITE-APPROVAL-TEST'}]
        for row in data['observations']:
            row['source_ids']=['ETCH-OBSERVATIONS']
        acquisition={'status':'AUDITED_READ_COMPLETED','environment':'INTERNAL_APPROVED_ONLY',
            'qualification_status':'QUALIFIED_INTERNAL','site_approval_reference':'SITE-APPROVAL-TEST',
            'audit_id':'AUDIT-TEST-1','audit_query_hash':'b'*64,'semantic_version':'SEM-7',
            'source_ids':['ETCH-OBSERVATIONS'],'source_hashes':{'ETCH-OBSERVATIONS':source_hash},'read_only':True}
        refused=analyze(data)
        self.assertEqual(refused['status'],'REFUSED')
        self.assertEqual(refused['mode'],'SYNTHETIC_DEMO')
        verified=analyze(data,acquisition=acquisition)
        self.assertIn(verified['status'],('VALID','PARTIAL'))
        self.assertEqual(verified['mode'],'INTERNAL_AUTHORIZED')
        self.assertEqual(verified['provenance']['authorization_reference'],'SITE-APPROVAL-TEST')
        self.assertIn('not independently authenticated',verified['limitations'][0])
        mismatched=copy.deepcopy(acquisition)
        mismatched['source_hashes']['ETCH-OBSERVATIONS']='c'*64
        self.assertEqual(analyze(data,acquisition=mismatched)['status'],'REFUSED')
if __name__=='__main__':unittest.main()
