"""Refresh release scan records for optional Python dependencies and product source.

Run from an isolated audit environment with pip-audit and Bandit installed.
The tools are qualification-only and are not product runtime dependencies.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DISPOSITIONS = {
    "B311": "Seeded pseudorandomness is used only for reproducible synthetic fixtures and DOE proposals, not secrets or security tokens.",
    "B404": "The configured MCP stdio transport starts an explicitly configured external process.",
    "B603": "MCP stdio startup uses a configured argument vector with shell=False and an explicitly mapped environment.",
    "B110": "Best-effort session cleanup suppresses only close-time errors after analysis; tool and permission failures remain visible.",
}


def run_json(command):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=240)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"scanner returned invalid JSON: {command[0]}") from exc
    return result, payload


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pip-audit", default="pip-audit")
    parser.add_argument("--bandit", default="bandit")
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    scanner = subprocess.run([args.pip_audit, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    dep_scopes = [
        ("qualification", [args.pip_audit, "-r", "qualification/benchmark-requirements.txt", "-f", "json"]),
        ("optional_mcp_sdk_macos_arm64_cp311", [args.pip_audit, "-r",
         "vendor/mcp-sdk/2.3.0/macos-arm64-cp311/requirements.lock", "--no-deps", "--require-hashes", "-f", "json"]),
    ]
    dependency_rows = []
    scope_results = []
    for scope, command in dep_scopes:
        result, payload = run_json(command)
        rows = payload.get("dependencies") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError(f"pip-audit dependency output malformed for {scope}")
        rows = [{"name": item["name"], "version": item["version"],
                 "vulnerabilities": item.get("vulns", []), "scope": scope} for item in rows]
        dependency_rows.extend(rows)
        vuln_count = sum(len(item["vulnerabilities"]) for item in rows)
        scope_results.append({"scope": scope, "return_code": result.returncode,
                              "dependency_instances": len(rows), "vulnerabilities_found": vuln_count,
                              "command": command})
    vulnerability_count = sum(len(item["vulnerabilities"]) for item in dependency_rows)
    unique_pairs = {(item["name"].lower(), item["version"]) for item in dependency_rows}
    dep_report = {
        "audit_timestamp_utc": now,
        "scanner": scanner,
        "advisory_source": "pip-audit default PyPI vulnerability service",
        "result": "PASS" if all(item["return_code"] == 0 for item in scope_results) and vulnerability_count == 0 else "FAIL",
        "scope": "All pinned optional benchmark/reference dependencies and the complete hash-locked optional MCP SDK tree; neither is a core product dependency.",
        "audit_environment": {"os": platform.platform(), "architecture": platform.machine(),
                              "python": platform.python_version(), "scanner_environment": "isolated qualification environment"},
        "dependency_instance_count": len(dependency_rows), "unique_name_version_count": len(unique_pairs),
        "vulnerabilities_found": vulnerability_count, "scope_results": scope_results,
        "scanned_dependencies": dependency_rows,
        "limitations": ["Does not scan the interpreter, OS/native system packages, source code, or legal rights.",
                        "A clean advisory lookup does not approve licenses, ownership, company transfer, or distribution."],
    }
    (ROOT / "release" / "DEPENDENCY_AUDIT.json").write_text(
        json.dumps(dep_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    bandit_version = subprocess.run([args.bandit, "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0].split()[-1]
    bandit_command = [args.bandit, "-r", "fabintel", "products/p4", "-f", "json", "--exit-zero"]
    bandit_result, raw = run_json(bandit_command)
    findings = raw.get("results", [])
    metrics = raw.get("metrics", {}).get("_totals", {})
    high_or_medium = sum(1 for item in findings if item.get("issue_severity") in ("HIGH", "MEDIUM"))
    finding_ids = {item.get("test_id") for item in findings}
    dispositioned = all(item in DISPOSITIONS for item in finding_ids)
    source_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                   capture_output=True, text=True, check=True).stdout.strip()
    scan_report = {
        "errors": raw.get("errors", []), "generated_at": now, "metrics": metrics,
        "results": findings,
        "review": {
            "command": "bandit -r fabintel products/p4 -f json --exit-zero",
            "tool": "Bandit", "tool_version": bandit_version,
            "finding_count": len(findings), "high_or_medium_findings": high_or_medium,
            "finding_dispositions_cover_all_reported_findings": dispositioned,
            "low_finding_dispositions": [{"test_id": key, "disposition": DISPOSITIONS[key]}
                                         for key in sorted(finding_ids) if key in DISPOSITIONS],
            "independent_human_source_review": "PENDING", "license_and_ownership_review": "PENDING",
            "limited_scan_result": "PASS_LIMITED_SCOPE" if not raw.get("errors") and high_or_medium == 0 and dispositioned else "FAIL",
            "limitations": "Static analysis does not replace manual threat modeling, OS/runtime review, penetration testing, or license and ownership review.",
            "product_source_commit": source_commit,
            "scanner_scope": "P4 runtime and product Python sources; excludes tests, fixtures, benchmark, and release tooling.",
        },
        "scanner_return_code": bandit_result.returncode,
    }
    (ROOT / "release" / "SOURCE_SECURITY_SCAN.json").write_text(
        json.dumps(scan_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"dependency_audit": dep_report["result"],
                      "dependency_instances": len(dependency_rows), "vulnerabilities_found": vulnerability_count,
                      "source_scan": scan_report["review"]["limited_scan_result"],
                      "source_findings": len(findings), "high_or_medium": high_or_medium}, indent=2))
    return 0 if dep_report["result"] == "PASS" and scan_report["review"]["limited_scan_result"] == "PASS_LIMITED_SCOPE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
