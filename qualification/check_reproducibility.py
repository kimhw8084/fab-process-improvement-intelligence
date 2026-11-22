"""Build twice and compare byte-for-byte archive hashes."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILDER = ROOT / "qualification" / "build_transfer_bundle.py"
ARCHIVE = ROOT / "release" / "FAB_INTELLIGENCE_P4_CANDIDATE.zip"
hashes = []
outputs = []
for _ in range(2):
    result = subprocess.run([sys.executable, str(BUILDER)], cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise SystemExit(result.stderr)
    outputs.append(result.stdout.strip())
    hashes.append(hashlib.sha256(ARCHIVE.read_bytes()).hexdigest())
report = {"status": "PASS" if hashes[0] == hashes[1] else "FAIL", "builds": 2,
          "archive": "release/FAB_INTELLIGENCE_P4_CANDIDATE.zip", "sha256_by_build": hashes,
          "commands": ["python qualification/build_transfer_bundle.py"] * 2,
          "method": "sorted paths, fixed ZIP timestamps, fixed file metadata, no generated output inside the archive"}
(ROOT / "release" / "BUILD_REPRODUCIBILITY.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2, sort_keys=True))
raise SystemExit(0 if report["status"] == "PASS" else 1)
