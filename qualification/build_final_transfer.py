"""Build the separate P4 final transfer candidate without replacing the preserved baseline."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "release" / "final"
ARCHIVE = OUTPUT / "P4_INTERNAL_TRANSFER_CANDIDATE.zip"
BASELINE_SHA256 = "ba7ef4fea8847f1563963772275dea3f0940737ea06fd421a97f464f33ff67ec"
SOURCE_MANIFEST_MEMBER = "release/SOURCE_MANIFEST.sha256"
SOURCE_BUILD_MEMBER = "release/SOURCE_BUILD.json"
FINAL_MANIFEST_MEMBER = "release/FINAL_TRANSFER_MANIFEST.json"

sys.path.insert(0, str(ROOT))
from qualification.build_transfer_bundle import require_clean_worktree, source_files  # noqa: E402


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _member_info(name):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o100644 & 0xFFFF) << 16
    info.flag_bits = 0
    return info


def build():
    require_clean_worktree()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    files = source_files()
    source = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in files}
    manifest = ("\n".join(f"{_sha(data)}  {name}" for name, data in sorted(source.items())) + "\n").encode()
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True).stdout.strip()
    build_metadata = (json.dumps({"schema": "p4-source-build/v1", "source_commit": commit,
        "source_file_count": len(source), "source_manifest_sha256": _sha(manifest),
        "secret_scan": {"implementation": "Golden scripts/secret_patterns.py",
                        "golden_commit": "dc2ece864b2d744e47dfe8c7d9ad78aadbed369e", "findings": 0},
        "qualification_scope": "local candidate source archive; not a distribution approval"},
        indent=2, sort_keys=True) + "\n").encode()
    report_path = ROOT / "release" / "FINAL_QUALIFICATION_REPORT.md"
    report_hash = _sha(report_path.read_bytes())
    embedded_manifest = {"schema": "p4-final-transfer/v1", "product_id": "p4",
        "release_state": "CANDIDATE", "source_commit": commit,
        "source_file_count": len(source), "source_manifest_sha256": _sha(manifest),
        "qualification_report": "release/FINAL_QUALIFICATION_REPORT.md",
        "qualification_report_sha256": report_hash,
        "preserved_baseline_sha256": BASELINE_SHA256,
        "formal_transfer_authorization": "PENDING_OWNER_AND_LEGAL_REVIEW",
        "archive_sha256": "See adjacent release/final/P4_INTERNAL_TRANSFER_CANDIDATE.sha256; intentionally not self-referential."}
    final_manifest = (json.dumps(embedded_manifest, indent=2, sort_keys=True) + "\n").encode()
    additions = {SOURCE_MANIFEST_MEMBER: manifest, SOURCE_BUILD_MEMBER: build_metadata,
                 FINAL_MANIFEST_MEMBER: final_manifest}
    packaged = {**source, **additions}
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9,
                         strict_timestamps=True) as bundle:
        for name, data in sorted(packaged.items()):
            bundle.writestr(_member_info(name), data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    digest = _sha(ARCHIVE.read_bytes())
    (OUTPUT / "P4_INTERNAL_TRANSFER_CANDIDATE.sha256").write_text(
        f"{digest}  {ARCHIVE.name}\n", encoding="utf-8")
    release_manifest = {**embedded_manifest, "archive_path": ARCHIVE.relative_to(ROOT).as_posix(),
                        "archive_sha256": digest, "archive_bytes": ARCHIVE.stat().st_size,
                        "member_count": len(packaged), "member_manifest_sha256": _sha(manifest)}
    (OUTPUT / "RELEASE_MANIFEST.json").write_text(json.dumps(release_manifest, indent=2, sort_keys=True) + "\n",
                                                  encoding="utf-8")
    verify(ARCHIVE, packaged, source, manifest, build_metadata, final_manifest)
    print(json.dumps({"status": "BUILT_CANDIDATE", "source_commit": commit,
        "source_files": len(source), "members": len(packaged), "archive_sha256": digest,
        "archive_bytes": ARCHIVE.stat().st_size, "source_manifest_sha256": _sha(manifest)},
        indent=2, sort_keys=True))
    return digest


def verify(archive, expected, source, manifest, build_metadata, final_manifest):
    with zipfile.ZipFile(archive) as bundle:
        names = [item.filename for item in bundle.infolist()]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("final archive inventory differs from the release manifest")
        for item in bundle.infolist():
            path = Path(item.filename)
            mode = (item.external_attr >> 16) & 0o170000
            if path.is_absolute() or ".." in path.parts or mode not in (0, 0o100000):
                raise ValueError(f"unsafe archive member: {item.filename}")
        if bundle.read(SOURCE_MANIFEST_MEMBER) != manifest:
            raise ValueError("source manifest member changed")
        if bundle.read(SOURCE_BUILD_MEMBER) != build_metadata or bundle.read(FINAL_MANIFEST_MEMBER) != final_manifest:
            raise ValueError("release manifest metadata changed")
        for name, data in source.items():
            if bundle.read(name) != data:
                raise ValueError(f"archive source differs from committed input: {name}")
    return True


if __name__ == "__main__":
    build()
