"""Qualify the exact final transfer archive from a fresh extraction."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _run(command, *, cwd, env=None, timeout=240):
    clean_env = dict(os.environ if env is None else env)
    clean_env.pop("PYTHONPATH", None)
    clean_env.update({"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    return subprocess.run(command, cwd=cwd, env=clean_env, capture_output=True, text=True, timeout=timeout)


def _extract_verified(archive, target, expected_sha):
    if _sha(archive.read_bytes()) != expected_sha:
        raise ValueError("final transfer archive checksum mismatch")
    with zipfile.ZipFile(archive) as bundle:
        names = [entry.filename for entry in bundle.infolist()]
        if len(names) != len(set(names)):
            raise ValueError("archive contains duplicate paths")
        for entry in bundle.infolist():
            name = PurePosixPath(entry.filename)
            mode = (entry.external_attr >> 16) & 0o170000
            if name.is_absolute() or ".." in name.parts or "\\" in entry.filename or mode not in (0, 0o100000):
                raise ValueError(f"archive contains an unsafe path: {entry.filename}")
        bundle.extractall(target)
    manifest = target / "release" / "SOURCE_MANIFEST.sha256"
    count = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", 1)
        name = PurePosixPath(relative)
        if name.is_absolute() or ".." in name.parts or "\\" in relative:
            raise ValueError(f"unsafe source manifest path: {relative}")
        item = target / relative
        if not item.is_file() or _sha(item.read_bytes()) != digest:
            raise ValueError(f"source manifest mismatch: {relative}")
        count += 1
    declared_names = {line.split("  ", 1)[1] for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()}
    package_names = set(names)
    expected_names = declared_names | {"release/SOURCE_MANIFEST.sha256", "release/SOURCE_BUILD.json",
                                       "release/FINAL_TRANSFER_MANIFEST.json"}
    if package_names != expected_names:
        raise ValueError("archive contains unmanifested files or omits required release metadata")
    build = json.loads((target / "release" / "SOURCE_BUILD.json").read_text(encoding="utf-8"))
    release = json.loads((target / "release" / "FINAL_TRANSFER_MANIFEST.json").read_text(encoding="utf-8"))
    report = target / release["qualification_report"]
    if (_sha(manifest.read_bytes()) != build.get("source_manifest_sha256")
            or build.get("source_commit") != release.get("source_commit")
            or _sha(report.read_bytes()) != release.get("qualification_report_sha256")
            or count != build.get("source_file_count")):
        raise ValueError("source build or release manifest does not match the extracted source")
    return count, build, release


def _python_path(venv_path):
    candidates = (venv_path / "bin" / "python", venv_path / "Scripts" / "python.exe")
    return next(path for path in candidates if path.exists())


def _core_runtime(interpreter, extracted, temp, index):
    environment = Path(temp) / f"core-{index}"
    created = _run([str(interpreter), "-m", "venv", "--without-pip", str(environment)], cwd=extracted)
    if created.returncode:
        raise RuntimeError(f"could not create no-pip venv for {interpreter}: {created.stderr[-500:]}")
    python = _python_path(environment)
    commands = [
        ("first_run", [str(python), "qualification/first_run.py", "--output", str(Path(temp) / f"first-run-{index}.json")]),
        ("doctor", [str(python), "-m", "fabintel", "doctor"]),
        ("demo", [str(python), "-m", "fabintel", "demo"]),
        ("analyze", [str(python), "-m", "fabintel", "analyze", "--input", "fixtures/full_workflow_demo.json"]),
    ]
    no_internet_profile = shutil.which("sandbox-exec") if sys.platform == "darwin" else None
    if no_internet_profile:
        commands = [(name, [no_internet_profile, "-n", "no-internet", *command])
                    for name, command in commands]
        commands.append(("egress_probe", [no_internet_profile, "-n", "no-internet", str(python),
                                           "qualification/network_deny_probe.py"]))
    outputs = {}
    for name, command in commands:
        result = _run(command, cwd=extracted, timeout=120)
        if result.returncode:
            raise RuntimeError(f"{name} failed with {interpreter}: {result.stderr[-800:]}")
        outputs[name] = json.loads(result.stdout)
    if "egress_probe" not in outputs:
        outputs["egress_probe"] = {"status": "UNVERIFIED_PLATFORM_POLICY_NOT_AVAILABLE",
                                   "network_access": "NOT_TESTED"}
    first_run = outputs["first_run"]
    if (first_run.get("status") != "PENDING_INTERNAL"
            or not all(first_run.get("static_checks", {}).values())
            or first_run.get("source_files_verified", 0) == 0):
        raise ValueError(f"first-run dependency/integrity check did not pass: {first_run}")
    if outputs["doctor"].get("state") != "CANDIDATE" or outputs["demo"].get("mode") != "SYNTHETIC_DEMO":
        raise ValueError("fresh extracted CLI returned an unexpected state")
    import importlib.util
    oracle_path = extracted / "qualification" / "workflow_qualification.py"
    spec = importlib.util.spec_from_file_location("p4_extracted_workflow_qualification", oracle_path)
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    qualified, statuses = oracle.analysis_result_is_qualified(outputs["analyze"])
    if not qualified:
        raise ValueError("fresh extracted scientific workflow failed")
    return {"python": str(interpreter), "version": outputs["first_run"].get("python_version"),
            "source_files_verified": first_run["source_files_verified"],
            "capability_statuses": statuses, "network_probe": outputs["egress_probe"],
            "status": "PASS_CORE_OFFLINE" if outputs["egress_probe"].get("status") == "DENIED"
            else "PASS_CORE_EGRESS_UNVERIFIED"}


def _offline_rollback_check(extracted, temp, index=0):
    envdir = Path(temp) / f"core-{index}"
    if not envdir.exists():
        raise RuntimeError("core runtime venv is unavailable for startup check")
    runtime = _python_path(envdir)
    import importlib.util
    browser_module_path = extracted / "qualification" / "standalone_ui_browser.py"
    spec = importlib.util.spec_from_file_location(f"p4_rollback_fixture_{index}", browser_module_path)
    browser_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(browser_module)
    synthetic_config = browser_module._synthetic_mcp_config()
    synthetic_config["transport"]["command"] = [str(runtime), "-m", "fabintel.mock_mcp_server"]
    synthetic_config["transport"]["cwd"] = str(extracted)
    synthetic_config_path = Path(temp) / f"rollback-synthetic-{index}.json"
    synthetic_config_path.write_text(json.dumps(synthetic_config), encoding="utf-8")
    process_env = dict(os.environ)
    process_env.pop("PYTHONPATH", None)
    process_env.update({"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})

    def start_and_stop(configured, expected_state):
        with socket.socket() as reserving:
            reserving.bind(("127.0.0.1", 0))
            port = reserving.getsockname()[1]
        command = [str(runtime), "-m", "fabintel", "serve", "--port", str(port)]
        if configured:
            command += ["--mcp-config", str(synthetic_config_path), "--allow-synthetic-mcp-test"]
        process = subprocess.Popen(command, cwd=extracted, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=process_env, text=True)
        ready = False
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/mcp/status", timeout=0.4) as response:
                        status = json.loads(response.read())
                        ready = response.status == 200 and status.get("state") == expected_state
                        break
                except OSError:
                    time.sleep(0.1)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=10)
        if not ready:
            raise RuntimeError(f"standalone server did not reach MCP state {expected_state}; "
                               f"returncode={process.returncode}; stdout={stdout[-500:]}; stderr={stderr[-500:]}")
        if process.returncode not in (0, 130, -2):
            raise RuntimeError(f"standalone server did not stop cleanly: {process.returncode}")

    start_and_stop(True, "READY")
    start_and_stop(False, "NOT_CONFIGURED")
    return {"status": "PASS", "actions": ["start with explicit synthetic test config",
        "verify configured state without invoking tools", "stop foreground process",
        "rollback to no MCP config", "verify local-only state", "restart and stop cleanly"]}


def _offline_sdk_browser(extracted, temp):
    sdk_envdir = Path(temp) / "sdk-browser"
    created = _run([sys.executable, "-m", "venv", "--system-site-packages", str(sdk_envdir)], cwd=extracted)
    if created.returncode:
        raise RuntimeError(f"could not create local browser qualification venv: {created.stderr[-500:]}")
    python = _python_path(sdk_envdir)
    asset = extracted / "vendor" / "mcp-sdk" / "2.3.0" / "macos-arm64-cp311"
    env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
           "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    installed = _run([str(python), "-m", "pip", "install", "--no-index", "--require-hashes",
                      "--find-links", str(asset / "wheelhouse"), "-r", str(asset / "requirements.lock")],
                     cwd=extracted, env=env)
    if installed.returncode:
        raise RuntimeError(f"SDK browser environment could not install offline: {installed.stderr[-800:]}")
    browser = _run([str(python), "qualification/standalone_ui_browser.py", "--output",
                    "release/final/P4_STANDALONE_UI_BROWSER.json"], cwd=extracted, env=env, timeout=180)
    if browser.returncode:
        raise RuntimeError(f"real-browser workflow failed from the final archive: {browser.stderr[-1000:]}")
    report = json.loads((extracted / "release/final/P4_STANDALONE_UI_BROWSER.json").read_text(encoding="utf-8"))
    expected_commit = json.loads((extracted / "release/SOURCE_BUILD.json").read_text(encoding="utf-8"))["source_commit"]
    import importlib.util
    evidence_path = extracted / "qualification" / "ui_evidence.py"
    spec = importlib.util.spec_from_file_location("p4_extracted_ui_evidence", evidence_path)
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    expected_hashes = {name: hashlib.sha256((extracted / name).read_bytes()).hexdigest()
                       for name in evidence.STANDALONE_SOURCE_PATHS}
    if not evidence.standalone_ui_evidence_matches(report, expected_commit, expected_hashes):
        raise ValueError("browser evidence is not bound to the exact extracted source or required workflow")
    return {"status": report["status"], "browser": report.get("browser"),
            "external_requests": report.get("external_requests"),
            "checks": report.get("checks"), "formal_accessibility": "PENDING_SCREEN_READER_WCAG_REVIEW"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--python", action="append", dest="pythons", default=[], help="target Python interpreter; may be repeated")
    parser.add_argument("--sha256-file", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    archive = args.archive.resolve()
    checksum_file = args.sha256_file.resolve() if args.sha256_file else archive.with_suffix(".sha256")
    line = checksum_file.read_text(encoding="utf-8").strip()
    expected_sha, filename = line.split("  ", 1)
    if filename != archive.name:
        raise SystemExit("checksum sidecar does not name the supplied final archive")
    interpreters = [Path(item).resolve() for item in args.pythons] or [Path(sys.executable).resolve()]
    report = {"status": "NOT_RUN", "archive": archive.name, "archive_sha256": expected_sha,
              "source_commit": None, "fresh_extract": True, "network_used_for_package_install": False,
              "core_platform_runs": [], "full_python_suite": {}, "mcp_sdk": {}, "browser": {}, "rollback": {}}
    try:
        with tempfile.TemporaryDirectory(prefix="p4-final-archive-qualify-") as temp:
            extracted = Path(temp) / "bundle"
            extracted.mkdir()
            source_count, build, release = _extract_verified(archive, extracted, expected_sha)
            report["source_commit"] = build["source_commit"]
            report["source_file_count"] = source_count
            report["release_manifest"] = release
            for index, interpreter in enumerate(interpreters):
                core = _core_runtime(interpreter, extracted, temp, index)
                core["startup_rollback"] = _offline_rollback_check(extracted, temp, index)
                report["core_platform_runs"].append(core)
            schema = _run([sys.executable, "qualification/schema_check.py"], cwd=extracted, timeout=120)
            report["schema_validation"] = json.loads(schema.stdout)
            if schema.returncode or report["schema_validation"].get("status") != "PASS":
                raise RuntimeError(f"extracted JSON schema validation failed: {schema.stderr[-800:]}")
            tests = _run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                         cwd=extracted, timeout=300)
            output = tests.stdout + tests.stderr
            match = re.search(r"Ran (\d+) tests? in ([0-9.]+)s", output)
            skipped = re.search(r"\(skipped=(\d+)\)", output)
            if tests.returncode or not match:
                raise RuntimeError(f"full suite failed on exact extracted source: {output[-1500:]}")
            report["full_python_suite"] = {"status": "PASS", "tests_run": int(match.group(1)),
                "skipped": int(skipped.group(1)) if skipped else 0,
                "skipped_scope": "optional MCP SDK protocol cases; separately qualified from bundled wheelhouse",
                "output_sha256": _sha(output.encode())}
            sdk = _run([sys.executable, "qualification/mcp_sdk_qualify.py"], cwd=extracted, timeout=300)
            report["mcp_sdk"] = json.loads(sdk.stdout)
            if sdk.returncode or report["mcp_sdk"].get("status") != "PASS_LOCAL_SYNTHETIC_MOCK_ONLY":
                raise RuntimeError(f"exact-archive MCP SDK offline qualification failed: {sdk.stderr[-1200:]}")
            report["browser"] = _offline_sdk_browser(extracted, temp)
        egress_denied = bool(report["core_platform_runs"]) and all(
            item.get("network_probe", {}).get("status") == "DENIED" for item in report["core_platform_runs"])
        report["status"] = "PASS_EXACT_ARCHIVE_LIMITED_PLATFORM" if egress_denied else "PENDING_EGRESS_POLICY"
        report["qualifies"] = ["fresh extraction and source manifest", "no-pip core install/runtime",
            "D01-D05 synthetic workflow", "offline pinned MCP SDK transport", "real Chromium UI workflow",
            "foreground stop and local-only restart on every supplied Python target"]
        if egress_denied:
            report["qualifies"].append("external egress denied by the named OS no-internet profile")
        else:
            report["limitations"].append("no portable caller OS egress-deny wrapper was available for all supplied interpreters")
        report["limitations"] = ["company target OS/OpenCode, permissions, semantics, data, security/legal approval, engineer acceptance, and production qualification remain pending"]
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"
    output_path = args.report.resolve() if args.report else ROOT / "release" / "final" / "ARCHIVE_QUALIFICATION.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS_EXACT_ARCHIVE_LIMITED_PLATFORM" else 1


if __name__ == "__main__":
    raise SystemExit(main())
