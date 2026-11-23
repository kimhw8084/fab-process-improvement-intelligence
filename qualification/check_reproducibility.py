"""Rebuild the exact committed source twice in separate clean worktrees."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILDER = "qualification/build_transfer_bundle.py"
ARCHIVE_NAME = "release/FAB_INTELLIGENCE_P4_CANDIDATE.zip"
MANIFEST_NAME = "release/SOURCE_MANIFEST.sha256"
CHECKSUM_NAME = "release/TRANSFER_BUNDLE.sha256"


def run(command, cwd=ROOT):
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    revision = run(["git", "rev-parse", "HEAD"])
    if revision.returncode:
        raise SystemExit(revision.stderr)
    source_commit = revision.stdout.strip()

    workspace_archive = ROOT / ARCHIVE_NAME
    workspace_manifest = (ROOT / MANIFEST_NAME).read_bytes()
    workspace_checksum = (ROOT / CHECKSUM_NAME).read_text(encoding="utf-8").strip()

    hashes = []
    manifests = []
    checksums = []
    with tempfile.TemporaryDirectory(prefix="fabintel-p4-clean-build-") as temporary:
        for index in range(2):
            worktree = Path(temporary) / f"source-{index + 1}"
            added = run(["git", "worktree", "add", "--detach", str(worktree), source_commit])
            if added.returncode:
                raise SystemExit(added.stderr)
            try:
                result = run([sys.executable, BUILDER], cwd=worktree)
                if result.returncode:
                    raise SystemExit(result.stderr)
                hashes.append(sha256(worktree / ARCHIVE_NAME))
                manifests.append((worktree / MANIFEST_NAME).read_bytes())
                checksums.append((worktree / CHECKSUM_NAME).read_text(encoding="utf-8").strip())
            finally:
                removed = run(["git", "worktree", "remove", "--force", str(worktree)])
                if removed.returncode:
                    raise SystemExit(removed.stderr)

    workspace_hash = sha256(workspace_archive)
    manifest_matches = workspace_manifest == manifests[0] == manifests[1]
    checksum_matches = workspace_checksum == f"{workspace_hash}  {workspace_archive.name}"
    status = "PASS" if (hashes[0] == hashes[1] == workspace_hash
                        and manifest_matches and checksum_matches) else "FAIL"
    report = {
        "status": status,
        "builds": 2,
        "archive": ARCHIVE_NAME,
        "source_commit": source_commit,
        "sha256_by_clean_build": hashes,
        "workspace_archive_sha256": workspace_hash,
        "workspace_archive_matches_clean_build": workspace_hash in hashes,
        "source_manifest_matches_clean_commit": manifest_matches,
        "sidecar_matches_workspace_archive": checksum_matches,
        "commands": ["git worktree add --detach <temporary-path> <source-commit>",
                     f"python {BUILDER}"] * 2,
        "source_manifest_hash_by_clean_build": [hashlib.sha256(value).hexdigest() for value in manifests],
        "sidecar_hash_by_clean_build": checksums,
        "method": "rebuild in two separate clean detached worktrees at the exact source commit; compare both builds, source manifests, sidecars, workspace ZIP and checksum",
    }
    (ROOT / "release" / "BUILD_REPRODUCIBILITY.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
