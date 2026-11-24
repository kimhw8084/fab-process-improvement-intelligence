"""Transfer-bundle first-run report; does not contact any internal or external service."""
import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from pathlib import PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _verify_source_manifest():
    manifest = ROOT / "release" / "SOURCE_MANIFEST.sha256"
    checked = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split("  ", 1)
        name = PurePosixPath(relative)
        if name.is_absolute() or ".." in name.parts or "\\" in relative:
            raise ValueError(f"unsafe source manifest path: {relative}")
        source = ROOT / relative
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError(f"source manifest mismatch: {relative}")
        checked += 1
    if checked == 0:
        raise ValueError("source manifest is empty")
    return checked


def _verify_mcp_wheelhouse():
    asset = ROOT / "vendor" / "mcp-sdk" / "2.3.0" / "macos-arm64-cp311"
    lock = asset / "requirements.lock"
    lines = [line.strip() for line in lock.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    hashes = {part.split(":", 1)[1] for line in lines for part in line.split()
              if part.startswith("--hash=sha256:")}
    wheels = sorted((asset / "wheelhouse").glob("*.whl"))
    if not lines or len(hashes) != len(lines) or len(wheels) != len(lines):
        raise ValueError("optional MCP SDK wheelhouse does not match its fully hashed lock")
    for wheel in wheels:
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if digest not in hashes:
            raise ValueError(f"optional MCP SDK wheel hash is not in its lock: {wheel.name}")
    return {"status": "PASS", "wheel_count": len(wheels), "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
            "target": "macOS ARM64 CPython 3.11 only",
            "host_compatible": platform.system() == "Darwin" and platform.machine() in ("arm64", "aarch64")
            and sys.version_info[:2] == (3, 11)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capability-report", help="local JSON snapshot emitted by an authorized internal bridge")
    parser.add_argument("--output", help="optional local path for the machine-readable report")
    args = parser.parse_args()
    report = {"product_id": "p4", "status": "PENDING_INTERNAL", "network_requests": 0,
              "python_version": sys.version.split()[0], "platform": f"{platform.system()} {platform.machine()}",
              "source_state": "CANDIDATE", "contract_version": "1.0.0", "static_checks": {},
              "company_qualification": "PENDING_INTERNAL",
              "unverified": ["real MCP identity and authorization", "approved source semantics and temporal joins",
                             "read-only bounded queries and audit/cancel", "target OS and approved UI host",
                             "approved model configuration", "engineer and security-owner acceptance"]}
    try:
        product = json.loads((ROOT / "product.json").read_text(encoding="utf-8"))
        report["static_checks"]["product_manifest"] = product.get("product_id") == "p4" and product.get("contract_version") == "1.0.0"
        for name in ("evidence.v1.schema.json", "product-manifest.v1.schema.json", "adapter-operations.v1.json"):
            value = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
            report["static_checks"][name] = bool(value)
        dependencies = product.get("dependencies", [])
        core_declaration = any("standard-library scientific core" in item for item in dependencies if isinstance(item, str))
        report["static_checks"]["offline_dependencies"] = core_declaration and sys.version_info >= (3, 10)
        report["static_checks"]["optional_mcp_bundle_present"] = bool(
            list((ROOT / "vendor" / "mcp-sdk" / "2.3.0" / "macos-arm64-cp311" / "wheelhouse").glob("*.whl")))
        report["source_files_verified"] = _verify_source_manifest()
        report["mcp_wheelhouse"] = _verify_mcp_wheelhouse()
        if args.capability_report:
            from fabintel.qualification import inspect_capability_report
            path = Path(args.capability_report)
            if path.stat().st_size > 256 * 1024:
                raise ValueError("capability report exceeds 256 KiB")
            compat = inspect_capability_report(json.loads(path.read_text(encoding="utf-8")))
            report["logical_compatibility"] = compat
        else:
            report["logical_compatibility"] = {"static_compatibility": "NOT_PROVIDED",
                                                "note": "Obtain an authorized internal capability snapshot; no endpoint or tool name is guessed here."}
        report["release_state"] = product.get("release_state", "CANDIDATE")
        report["release_state_source"] = "product.json; generated gate sidecars are not required for offline first-run"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report["status"] = "ERROR"
        report["error"] = str(exc)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 1 if report["status"] == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
