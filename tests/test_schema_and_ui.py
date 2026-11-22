import unittest,json
from pathlib import Path
class SourceContractTests(unittest.TestCase):
 def test_schema_files_identify_version(self):
  root=Path(__file__).resolve().parent.parent
  for name in ('evidence.v1.schema.json','product-manifest.v1.schema.json'):
   doc=json.loads((root/'contracts'/name).read_text())
   self.assertIn('1.0.0',doc['$id'])
 def test_manifest_declares_bootstrap_only(self):
  root=Path(__file__).resolve().parent.parent
  manifest=json.loads((root/'product.json').read_text())
  self.assertEqual(manifest['release_state'],'CANDIDATE')
  self.assertEqual(manifest['contract_version'],'1.0.0')
 def test_no_remote_frontend_assets(self):
  root=Path(__file__).resolve().parent.parent
  html=(root/'ui'/'index.html').read_text()
  for forbidden in ('src="http://','src="https://','href="http://','href="https://','@import url(http'):
   self.assertNotIn(forbidden,html)
