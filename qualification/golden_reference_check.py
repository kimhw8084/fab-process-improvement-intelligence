"""Replay the pinned Golden doctor, fast check, and P4-relevant task routes offline."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "research" / "golden-agentic-engineering"
SOURCE = REFERENCE / "source"
def verify_snapshot():
    manifest = json.loads((REFERENCE / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    errors = []
    for relative, expected in manifest["copied_files"].items():
        path = SOURCE / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            errors.append(relative)
    if errors:
        raise ValueError("Pinned Golden source snapshot hash mismatch: " + ", ".join(errors))
    release = json.loads((SOURCE / "standards" / "release.json").read_text(encoding="utf-8"))
    if release.get("status") != "PILOT_UNQUALIFIED":
        raise ValueError("Golden qualification state changed; review before reusing this check")
    routing = json.loads((SOURCE / "workflows" / "task-routing.json").read_text(encoding="utf-8"))
    route_ids = {item.get("id") for item in routing.get("workflows", []) if isinstance(item, dict)}
    if not {"react-app-feature", "manufacturing-analytics", "release-qualification"} <= route_ids:
        raise ValueError("Pinned task-routing catalog is missing a P4-relevant route")
    return manifest, release


def run(command):
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
    return result


def main():
    manifest, golden_release = verify_snapshot()
    proof = SOURCE / "scripts" / "golden.py"
    doctor = run([sys.executable, str(proof), "doctor", "--project", str(ROOT)])
    evidence = json.loads((ROOT / "golden.project.json").read_text(encoding="utf-8"))
    check = run([sys.executable, str(proof), "check", "--fast", "--project", str(ROOT),
                 "--out", str(ROOT / "qualification" / "evidence" / ".golden-fast.json")])
    generated_path = ROOT / "qualification" / "evidence" / ".golden-fast.json"
    try:
        fast_evidence = json.loads(generated_path.read_text(encoding="utf-8"))
    finally:
        generated_path.unlink(missing_ok=True)
    result = {
        "status": "PASS_REFERENCE_CHECKS_PRE_QUALIFICATION" if doctor.returncode == 0 and check.returncode == 0
                 and fast_evidence.get("qualifies_release") is False else "FAIL",
        "scope": "pinned Golden local developer checks and P4-relevant routing; not P4 release qualification",
        "golden": {"repository": manifest["repository"], "commit": manifest["commit"],
                   "version": golden_release["version"], "status": golden_release["status"],
                   "rules_sha256": fast_evidence.get("rules_sha256"),
                   "snapshot_files_verified": len(manifest["copied_files"])},
        "project_manifest": {"profile": evidence["profile"], "capabilities": evidence["capabilities"]},
        "doctor": {"return_code": doctor.returncode, "summary": doctor.stdout.strip().splitlines()},
        "fast_check": {"return_code": check.returncode, "mode": fast_evidence.get("mode"),
                       "qualifies_release": fast_evidence.get("qualifies_release"),
                       "status_counts": {status: sum(row["status"] == status for row in fast_evidence["results"])
                                         for status in sorted({row["status"] for row in fast_evidence["results"]})},
                       "results": fast_evidence.get("results", [])},
        "p4_relevant_routes_present": ["react-app-feature", "manufacturing-analytics", "release-qualification"],
        "not_run": ["Golden full check", "route resolver integration (unneeded OpenCode agents are not vendored)",
                    "Golden upstream fixture suite", "company OpenCode and target-host qualification"],
        "disclaimer": "Golden v0.1.0-dev is PRE_QUALIFICATION; passing local checks do not mean Golden requirements are fully implemented or enforced.",
    }
    path = ROOT / "qualification" / "evidence" / "golden-reference-checks-2026-11-22.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "golden_state": golden_release["status"],
                      "fast_check_qualifies_release": result["fast_check"]["qualifies_release"],
                      "snapshot_files_verified": len(manifest["copied_files"]), "report": str(path)}, indent=2))
    return 0 if result["status"] == "PASS_REFERENCE_CHECKS_PRE_QUALIFICATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
