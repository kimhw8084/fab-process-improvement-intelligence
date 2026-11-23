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
 def test_file_picker_keyboard_focus_is_visible_on_its_label(self):
  root=Path(__file__).resolve().parent.parent
  html=(root/'ui'/'index.html').read_text()
  input_markup='<input id="request-file" type="file" accept="application/json,.json"><label class="file-label" for="request-file">Open JSON file</label>'
  focus_rule='input[type=file]:focus-visible+.file-label{outline:3px solid #168b76;outline-offset:3px}'
  self.assertIn(input_markup,html)
  self.assertIn(focus_rule,html)
