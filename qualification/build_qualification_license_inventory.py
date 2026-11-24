"""Record raw license metadata for the resolved, qualification-only Python tree."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import re
import sys

ROOT = Path(__file__).resolve().parent.parent


def main():
    audit = json.loads((ROOT / "release" / "DEPENDENCY_AUDIT.json").read_text(encoding="utf-8"))
    packages = []
    for item in audit.get("scanned_dependencies", []):
        if item.get("scope") != "qualification":
            continue
        try:
            dist = metadata.distribution(item["name"])
        except metadata.PackageNotFoundError as exc:
            raise SystemExit(f"qualification package is absent from the audit environment: {item['name']}") from exc
        if dist.version != item["version"]:
            raise SystemExit(f"qualification package version differs from advisory scan: {item['name']}")
        license_files = []
        for entry in dist.files or ():
            filename = Path(str(entry)).name
            if not re.search(r"(^|[._-])(license|licence|copying|notice|copyright)([._-]|$)", filename, re.IGNORECASE):
                continue
            path = dist.locate_file(entry)
            if path.is_file() and path.stat().st_size <= 1_000_000:
                license_files.append({"filename": filename, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        raw_license = dist.metadata.get("License") or ""
        expression = dist.metadata.get("License-Expression") or ""
        classifiers = sorted(value for value in dist.metadata.get_all("Classifier", [])
                             if value.startswith("License ::"))
        packages.append({"name": dist.metadata.get("Name", item["name"]), "version": dist.version,
            "purl": f"pkg:pypi/{re.sub(r'[-_.]+', '-', item['name']).lower()}@{dist.version}",
            "spdx_expression": expression or None, "raw_license_metadata": raw_license or None,
            "license_classifiers": classifiers, "license_file_artifacts": sorted(license_files, key=lambda row: row["filename"])})
    packages.sort(key=lambda row: (row["name"].lower(), row["version"]))
    if len(packages) != len([item for item in audit.get("scanned_dependencies", []) if item.get("scope") == "qualification"]):
        raise SystemExit("resolved qualification license inventory is incomplete")
    inventory = {"schema": "p4-qualification-license-inventory/v1",
        "scope": "Resolved qualification/reference packages only; these wheels are not bundled and are not P4 runtime dependencies.",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_audit_timestamp_utc": audit.get("audit_timestamp_utc"),
        "advisory_scanner": audit.get("scanner"),
        "inventory_host": {"os": platform.platform(), "architecture": platform.machine(), "python": sys.version.split()[0]},
        "package_count": len(packages), "packages": packages,
        "limitations": ["Raw installed metadata and license-file hashes are evidence, not legal interpretation or approval.",
                        "This inventory does not provide offline wheels for the qualification-only dependency tree."]}
    output = ROOT / "release" / "QUALIFICATION_DEPENDENCY_LICENSE_INVENTORY.json"
    output.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "packages": len(packages), "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
