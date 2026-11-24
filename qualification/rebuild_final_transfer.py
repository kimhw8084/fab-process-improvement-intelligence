"""Build the final transfer archive in two clean detached worktrees and compare exact bytes."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = Path("release/final/P4_INTERNAL_TRANSFER_CANDIDATE.zip")
MANIFEST = Path("release/final/RELEASE_MANIFEST.json")
BUILDER = "qualification/build_final_transfer.py"


def _run(args, cwd=ROOT):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    commit = _run(["git", "rev-parse", "HEAD"])
    if commit.returncode:
        raise SystemExit(commit.stderr)
    revision = commit.stdout.strip()
    workspace_zip = ROOT / ARCHIVE
    workspace_manifest = (ROOT / MANIFEST).read_bytes()
    workspace_hash = _sha(workspace_zip)
    builds = []
    with tempfile.TemporaryDirectory(prefix="p4-final-repro-") as temp:
        for index in range(2):
            worktree = Path(temp) / f"source-{index + 1}"
            add = _run(["git", "worktree", "add", "--detach", str(worktree), revision])
            if add.returncode:
                raise SystemExit(add.stderr)
            try:
                build = _run([sys.executable, BUILDER], cwd=worktree)
                if build.returncode:
                    raise SystemExit(build.stderr)
                archive_path, manifest_path = worktree / ARCHIVE, worktree / MANIFEST
                builds.append({"sha256": _sha(archive_path),
                               "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                               "bytes": archive_path.stat().st_size})
            finally:
                remove = _run(["git", "worktree", "remove", "--force", str(worktree)])
                if remove.returncode:
                    raise SystemExit(remove.stderr)
    reproducible = (len(builds) == 2 and builds[0] == builds[1]
                    and workspace_hash == builds[0]["sha256"]
                    and hashlib.sha256(workspace_manifest).hexdigest() == builds[0]["manifest_sha256"])
    report = {"status": "PASS" if reproducible else "FAIL", "source_commit": revision,
        "builds": builds, "workspace_archive_sha256": workspace_hash,
        "workspace_matches_clean_builds": reproducible,
        "method": "Two independent detached worktrees at the exact source commit; compare archive, manifest, and workspace bytes."}
    target = ROOT / "release" / "final" / "BUILD_REPRODUCIBILITY.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if reproducible else 1


if __name__ == "__main__":
    raise SystemExit(main())
