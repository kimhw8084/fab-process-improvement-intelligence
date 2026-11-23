"""Create and verify P4's deterministic, tracked-source offline ZIP."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "release"
ARCHIVE = RELEASE / "FAB_INTELLIGENCE_P4_CANDIDATE.zip"
MANIFEST = RELEASE / "SOURCE_MANIFEST.sha256"
CHECKSUM = RELEASE / "TRANSFER_BUNDLE.sha256"
BUILD_METADATA = RELEASE / "SOURCE_BUILD.json"
GOLDEN_TOOLS = ROOT / "research" / "golden-agentic-engineering" / "source" / "scripts"
sys.path.insert(0, str(GOLDEN_TOOLS))
from secret_patterns import scan_text  # noqa: E402

EXCLUDED = {ARCHIVE, CHECKSUM, RELEASE / "RELEASE_REPORT.md", RELEASE / "OFFLINE_QUALIFICATION.json",
            RELEASE / "BUILD_REPRODUCIBILITY.json", RELEASE / "GATE_REPORT.json",
            RELEASE / "TEST_LOG.txt", RELEASE / "TEST_RESULTS.json", BUILD_METADATA,
            RELEASE / "SCHEMA_VALIDATION.json", RELEASE / "BENCHMARK_REPORT.json"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
# Workspace-only execution ledgers are kept beside the source but are not product transfer contents.
EXCLUDED_SOURCE_PREFIXES = ("qualification/evidence/legacy/", "qualification/results/", "progress/")
# Mutable qualification outputs stay beside the product archive as evidence sidecars;
# they are not runtime inputs and must not make a clean-source rebuild self-referential.
GENERATED_OUTPUT_FILES = {path.relative_to(ROOT).as_posix() for path in EXCLUDED | {MANIFEST}}


def is_generated_qualification_output(relative_path):
    """Return whether a mutable build or qualification output is outside product source."""
    return relative_path in GENERATED_OUTPUT_FILES or relative_path.startswith("qualification/results/")


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def require_clean_worktree():
    status_result = subprocess.run(["git", "-C", str(ROOT), "-c", "core.quotePath=false", "status",
                                    "--porcelain", "--untracked-files=all"], check=True,
                                   capture_output=True, text=True)
    status = status_result.stdout
    unexpected = []
    for entry in status.splitlines():
        relative = entry[3:]
        if " -> " in relative:
            relative = relative.rsplit(" -> ", 1)[1]
        if not is_generated_qualification_output(relative):
            unexpected.append(entry)
    if unexpected:
        raise ValueError("Refusing to build with uncommitted product source changes: " + "; ".join(unexpected[:8]))


def source_files():
    raw = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], check=True,
                         capture_output=True).stdout
    files = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        path = ROOT / os.fsdecode(item)
        relative_parts = path.relative_to(ROOT).parts
        relative = path.relative_to(ROOT).as_posix()
        if path in EXCLUDED or path == MANIFEST:
            continue
        if relative.startswith(EXCLUDED_SOURCE_PREFIXES):
            continue
        if any(part in SKIP_DIRS for part in relative_parts):
            continue
        if path.name == ".DS_Store":
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"symlinks are not allowed in the transfer bundle: {path.relative_to(ROOT)}")
        contents = path.read_bytes()
        findings = scan_text(contents.decode("utf-8", errors="ignore"), path.relative_to(ROOT).as_posix())
        if findings:
            labels = ", ".join(f"{row['kind']}@{row['line']}" for row in findings[:8])
            raise ValueError(f"Golden secret-pattern scan found a potential secret in {path.relative_to(ROOT)}: {labels}")
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def main():
    require_clean_worktree()
    files = source_files()
    manifest_lines = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(ROOT).as_posix()}" for path in files]
    manifest_text = "\n".join(manifest_lines) + "\n"
    MANIFEST.write_text(manifest_text, encoding="utf-8")
    source_commit = git("rev-parse", "HEAD")
    metadata = {"schema": "p4-source-build/v1", "source_commit": source_commit,
                "source_file_count": len(files),
                "source_manifest_sha256": hashlib.sha256(manifest_text.encode("utf-8")).hexdigest(),
                "secret_scan": {"implementation": "Golden scripts/secret_patterns.py",
                                "golden_commit": "dc2ece864b2d744e47dfe8c7d9ad78aadbed369e", "findings": 0},
                "qualification_scope": "local candidate source archive; not a distribution approval"}
    metadata_text = json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    BUILD_METADATA.write_text(metadata_text, encoding="utf-8")
    packaged = files + [MANIFEST, BUILD_METADATA]
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as bundle:
        for path in sorted(packaged, key=lambda item: item.relative_to(ROOT).as_posix()):
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            info.flag_bits = 0
            bundle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    archive_hash = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    CHECKSUM.write_text(f"{archive_hash}  {ARCHIVE.name}\n", encoding="utf-8")
    verify_archive(ARCHIVE)
    print(f"SOURCE_COMMIT={source_commit}")
    print(f"SOURCE_FILES={len(files)}")
    print(f"ZIP_SHA256={archive_hash}")
    print(f"ZIP_BYTES={ARCHIVE.stat().st_size}")
    print("SOURCE_MANIFEST=release/SOURCE_MANIFEST.sha256 (manifest does not hash itself or the archive)")
    return 0


def verify_archive(archive):
    expected = {path.relative_to(ROOT).as_posix(): path for path in source_files()}
    expected.update({MANIFEST.relative_to(ROOT).as_posix(): MANIFEST,
                     BUILD_METADATA.relative_to(ROOT).as_posix(): BUILD_METADATA})
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("ZIP inventory differs from the tracked source manifest")
        for info in infos:
            if info.is_dir() or info.filename.startswith("/") or ".." in Path(info.filename).parts:
                raise ValueError(f"unsafe ZIP member: {info.filename}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode not in (0, 0o100000):
                raise ValueError(f"non-regular ZIP member: {info.filename}")
        manifest = bundle.read(MANIFEST.relative_to(ROOT).as_posix()).decode("utf-8")
        declared = {}
        for line in manifest.splitlines():
            digest, relative = line.split("  ", 1)
            declared[relative] = digest
        if set(declared) != set(expected) - {MANIFEST.relative_to(ROOT).as_posix(), BUILD_METADATA.relative_to(ROOT).as_posix()}:
            raise ValueError("source manifest does not cover the exact tracked-source inventory")
        for relative, path in expected.items():
            contents = bundle.read(relative)
            if relative in declared and hashlib.sha256(contents).hexdigest() != declared[relative]:
                raise ValueError(f"source digest mismatch in ZIP: {relative}")
            if relative not in (MANIFEST.relative_to(ROOT).as_posix(), BUILD_METADATA.relative_to(ROOT).as_posix()) and contents != path.read_bytes():
                raise ValueError(f"ZIP content differs from source snapshot: {relative}")
    return True


if __name__ == "__main__":
    raise SystemExit(main())
