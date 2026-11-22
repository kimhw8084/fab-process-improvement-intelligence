"""Check the current candidate source manifest, then run its complete test suite."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def verify_manifest(manifest):
    checks = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, rel = line.split("  ", 1)
        path = ROOT / rel
        if not path.is_file():
            raise SystemExit(f"INTEGRITY FAILED: missing {rel}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"INTEGRITY FAILED: {rel}")
        checks += 1
    return checks


def main():
    current = ROOT / "release" / "SOURCE_MANIFEST.sha256"
    product = json.loads((ROOT / "product.json").read_text(encoding="utf-8"))
    if current.exists():
        print("SOURCE INTEGRITY PASS:", verify_manifest(current), "files")
    elif product.get("release_state") == "BOOTSTRAP_ONLY":
        old = ROOT / "release" / "BOOTSTRAP_MANIFEST.sha256"
        print("BOOTSTRAP INTEGRITY PASS:", verify_manifest(old), "files")
    else:
        print("SOURCE INTEGRITY NOT RECORDED: build the candidate manifest before transfer.")
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT)
    if tests.returncode:
        raise SystemExit(tests.returncode)
    print("SCIENTIFIC AND PRODUCT TESTS PASS; release status is recorded separately in release/GATE_REPORT.json")


if __name__ == "__main__":
    main()
