"""Fresh-extract, no-pip runtime check. Invoke under an OS network-deny sandbox."""
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent


def verify_source_manifest(root):
    manifest = root / "release" / "SOURCE_MANIFEST.sha256"
    checked = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, rel = line.split("  ", 1)
        name = PurePosixPath(rel)
        if name.is_absolute() or ".." in name.parts or "\\" in rel:
            raise ValueError(f"unsafe source manifest path: {rel}")
        candidate = root / rel
        if not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:
            raise ValueError(f"source manifest mismatch: {rel}")
        checked += 1
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    archive = args.archive.resolve()
    try:
        archive_label = archive.relative_to(ROOT).as_posix()
    except ValueError:
        archive_label = archive.name
    report = {"state": "NOT_RUN", "host": {"os": platform.platform(), "machine": platform.machine(), "python": sys.version},
              "archive": archive_label, "archive_sha256": None, "archive_checksum_verified": False,
              "source_files_verified": 0,
              "install_mode": "fresh ZIP extraction + venv without pip", "network_policy": "must be enforced by caller OS sandbox"}
    try:
        report["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix="fabintel-p4-offline-") as temp:
            extracted = Path(temp) / "bundle"
            extracted.mkdir()
            with zipfile.ZipFile(archive) as bundle:
                for item in bundle.infolist():
                    name = PurePosixPath(item.filename)
                    if name.is_absolute() or ".." in name.parts or "\\" in item.filename:
                        raise ValueError("archive contains an unsafe path")
                bundle.extractall(extracted)
            checksum_path = ROOT / "release" / "TRANSFER_BUNDLE.sha256"
            expected_line = f"{report['archive_sha256']}  {archive.name}"
            if checksum_path.read_text(encoding="utf-8").strip() != expected_line:
                raise ValueError("adjacent transfer checksum does not match the archive")
            report["archive_checksum_verified"] = True
            report["source_files_verified"] = verify_source_manifest(extracted)
            envdir = Path(temp) / "venv"
            venv.EnvBuilder(with_pip=False, clear=True).create(envdir)
            python = envdir / "bin" / "python"
            env = {**os.environ, "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
            commands = [
                [str(python), "-m", "fabintel", "doctor"],
                [str(python), "-m", "fabintel", "demo"],
                [str(python), "-m", "fabintel", "analyze", "--input", "fixtures/full_workflow_demo.json"],
                [str(python), "qualification/network_deny_probe.py"],
            ]
            outputs = []
            for command in commands:
                result = subprocess.run(command, cwd=extracted, env=env, text=True, capture_output=True, timeout=60)
                if result.returncode:
                    raise RuntimeError(f"offline command failed: {' '.join(command)}: {result.stderr[-1000:]}")
                outputs.append(json.loads(result.stdout))
            if outputs[0].get("state") != "CANDIDATE" or outputs[1].get("mode") != "SYNTHETIC_DEMO":
                raise ValueError("doctor/demo returned unexpected release state")
            final = outputs[2]
            if final.get("status") != "VALID" or final.get("product_id") != "p4":
                raise ValueError("full synthetic dossier did not complete")
            dossier = final["artifacts"][0]
            if not all(k in dossier for k in ("D01_sensitivity", "D02_observed_process_window", "D03_tradeoffs", "D04_experiment_proposal", "D05_effectiveness")):
                raise ValueError("full workflow artifact is incomplete")
            report["commands"] = ["python -m fabintel doctor", "python -m fabintel demo",
                                   "python -m fabintel analyze --input fixtures/full_workflow_demo.json",
                                   "python qualification/network_deny_probe.py"]
            report["result"] = "PASS"
            report["state"] = "PASS"
            report["dependency_install"] = "none; fresh venv has no pip and no third-party packages"
            report["workflow_status"] = final["status"]
            report["network_policy_probe"] = outputs[3]
            if outputs[3].get("status") != "DENIED":
                raise ValueError("network-deny socket probe did not confirm sandbox denial")
    except Exception as exc:
        report["result"] = "FAIL"
        report["state"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"
    output = ROOT / "release" / "OFFLINE_QUALIFICATION.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report.get("result") != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
