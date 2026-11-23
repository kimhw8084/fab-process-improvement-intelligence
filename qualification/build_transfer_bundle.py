"""Create a sorted, timestamp-normalized, self-contained candidate ZIP."""
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "release"
ARCHIVE = RELEASE / "FAB_INTELLIGENCE_P4_CANDIDATE.zip"
MANIFEST = RELEASE / "SOURCE_MANIFEST.sha256"
CHECKSUM = RELEASE / "TRANSFER_BUNDLE.sha256"
EXCLUDED = {ARCHIVE, CHECKSUM, RELEASE / "RELEASE_REPORT.md", RELEASE / "OFFLINE_QUALIFICATION.json",
            RELEASE / "BUILD_REPRODUCIBILITY.json", RELEASE / "GATE_REPORT.json",
            RELEASE / "TEST_LOG.txt", RELEASE / "TEST_RESULTS.json",
            RELEASE / "SCHEMA_VALIDATION.json"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}


def source_files():
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path in EXCLUDED or path == MANIFEST:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.name == ".DS_Store":
            continue
        if path.is_symlink():
            raise ValueError(f"symlinks are not allowed in the transfer bundle: {path.relative_to(ROOT)}")
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def main():
    files = source_files()
    manifest_lines = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(ROOT).as_posix()}" for path in files]
    MANIFEST.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    packaged = files + [MANIFEST]
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
    print(f"SOURCE_FILES={len(files)}")
    print(f"ZIP_SHA256={archive_hash}")
    print(f"ZIP_BYTES={ARCHIVE.stat().st_size}")
    print("SOURCE_MANIFEST=release/SOURCE_MANIFEST.sha256 (manifest does not hash itself or the archive)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
