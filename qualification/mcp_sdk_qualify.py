"""Install the pinned optional MCP SDK only from its local wheelhouse and test its mock transports."""
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ASSET = ROOT / "vendor" / "mcp-sdk" / "2.3.0" / "macos-arm64-cp311"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, *, cwd, env=None):
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=240)


def main():
    report = {
        "status": "NOT_RUN",
        "scope": "optional MCP SDK offline wheel installation and P4 synthetic stdio/Streamable HTTP transport, mapping, and metadata-discovery tests",
        "target": {"os": platform.system(), "architecture": platform.machine(),
                   "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"},
        "asset": "vendor/mcp-sdk/2.3.0/macos-arm64-cp311",
        "network_used": False,
    }
    try:
        if (platform.system() != "Darwin" or platform.machine() not in ("arm64", "aarch64")
                or sys.version_info[:2] != (3, 11)):
            report["status"] = "NOT_RUN_UNSUPPORTED_TARGET"
            report["reason"] = "This wheelhouse targets macOS ARM64 and CPython 3.11 only."
            raise RuntimeError("unsupported qualification target")
        lock = ASSET / "requirements.lock"
        wheelhouse = ASSET / "wheelhouse"
        lines = [line.strip() for line in lock.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        if not lines or any("--hash=sha256:" not in line for line in lines):
            raise ValueError("every dependency lock entry must include a SHA-256 hash")
        wheels = sorted(wheelhouse.glob("*.whl"))
        if len(wheels) != len(lines) or not wheels:
            raise ValueError("wheel count does not match the fully hashed dependency lock")
        report["lock_sha256"] = sha256(lock)
        report["wheel_count"] = len(wheels)
        report["wheel_bytes"] = sum(path.stat().st_size for path in wheels)
        with tempfile.TemporaryDirectory(prefix="p4-mcp-wheel-qualify-") as temporary:
            temp = Path(temporary)
            envdir = temp / "venv"
            venv.EnvBuilder(with_pip=True, clear=True).create(envdir)
            python = envdir / "bin" / "python"
            env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                   "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
            install = run([str(python), "-m", "pip", "install", "--no-index", "--require-hashes",
                           "--find-links", str(wheelhouse), "-r", str(lock)], cwd=ROOT, env=env)
            report["install_return_code"] = install.returncode
            report["install_output_sha256"] = hashlib.sha256((install.stdout + install.stderr).encode()).hexdigest()
            if install.returncode:
                raise RuntimeError("offline --require-hashes installation failed")
            version = run([str(python), "-c", "from importlib.metadata import version; print(version('mcp'))"],
                          cwd=ROOT, env=env)
            report["installed_mcp_version"] = version.stdout.strip()
            if version.returncode or version.stdout.strip() != "2.3.0":
                raise RuntimeError("installed MCP SDK version did not match the pinned candidate")
            tests = run([str(python), "-m", "unittest", "discover", "-s", "tests",
                         "-p", "test_mcp_*.py", "-v"], cwd=ROOT, env=env)
            output = tests.stdout + tests.stderr
            match = re.search(r"Ran (\d+) tests? in ([0-9.]+)s", output)
            report["protocol_test_return_code"] = tests.returncode
            report["protocol_tests_run"] = int(match.group(1)) if match else None
            report["protocol_test_output_sha256"] = hashlib.sha256(output.encode()).hexdigest()
            if tests.returncode or not match or "skipped=" in output or "OK" not in output:
                raise RuntimeError("the SDK protocol tests did not all pass without skips")
        report["status"] = "PASS_LOCAL_SYNTHETIC_MOCK_ONLY"
        report["transport_qualification"] = ["stdio", "Streamable HTTP"]
        report["company_compatibility"] = "PENDING_INTERNAL"
        report["limitations"] = ["synthetic server only", "no company endpoint, semantics, permissions, or credentials",
                                 "this local-loopback transport test does not qualify an OS egress policy"]
    except Exception as exc:
        if report["status"] != "NOT_RUN_UNSUPPORTED_TARGET":
            report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"
    output_path = ROOT / "release" / "MCP_SDK_QUALIFICATION.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS_LOCAL_SYNTHETIC_MOCK_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
