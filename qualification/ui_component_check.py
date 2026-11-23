"""Exercise the P4 React module with the P1-owned local toolchain.

Pass --suite-root pointing at a checkout containing P1's pinned package-lock,
vite.config.ts, and node_modules. This checks a headless module only; it does
not create or qualify a suite host.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(command, cwd):
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=120)
    return {"return_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-root", type=Path, required=True)
    args = parser.parse_args()
    suite = args.suite_root.resolve()
    suite_package = suite / "package.json"
    suite_lock = suite / "package-lock.json"
    vite_config = suite / "vite.config.ts"
    if not all(path.is_file() for path in (suite_package, suite_lock, vite_config)):
        raise SystemExit("P1 suite package.json, package-lock.json, and vite.config.ts are required")
    modules = ROOT / "node_modules"
    created_link = False
    if modules.exists() or modules.is_symlink():
        if not modules.is_symlink() or modules.resolve() != (suite / "node_modules").resolve():
            raise SystemExit("P4 node_modules already exists; refusing to replace product dependencies")
    else:
        modules.symlink_to(suite / "node_modules", target_is_directory=True)
        created_link = True
    try:
        component_test = run(["npm", "exec", "--", "vitest", "run", "--reporter=dot", "--root", str(ROOT),
                              "--config", str(vite_config), "products/p4/ui/P4Panel.test.tsx"], suite)
        typecheck = run(["npm", "exec", "--", "tsc", "--noEmit", "--strict", "--skipLibCheck",
                         "--target", "ES2022", "--module", "ESNext", "--moduleResolution", "Bundler",
                         "--jsx", "react-jsx", "--lib", "ES2022,DOM", "--types",
                         "vitest/globals,@testing-library/jest-dom",
                         str(ROOT / "products/p4/ui/P4Panel.tsx"),
                         str(ROOT / "products/p4/ui/P4Panel.test.tsx")], suite)
    finally:
        if created_link:
            modules.unlink()
    summary = re.search(r"Tests\s+(\d+) passed", component_test["stdout"] + component_test["stderr"])
    tests_passed = int(summary.group(1)) if summary else None
    reference = json.loads((ROOT / "research/p1-suite-ui-reference/REFERENCE.json").read_text(encoding="utf-8"))
    contract_matches = all(digest(suite / "contracts" / name) == reference["contracts"][name]["sha256"]
                           for name in ("suite-ui-module.v1.schema.json", "suite-chart.v1.schema.json"))
    suite_manifest = json.loads(suite_package.read_text(encoding="utf-8"))
    report = {
        "status": "PASS_LOCAL_MODULE_ONLY" if component_test["return_code"] == 0 and tests_passed == 8
                  and typecheck["return_code"] == 0 and contract_matches else "FAIL",
        "scope": "headless P4 React module against local P1 schemas and P1 test toolchain; no suite host or target OS tested",
        "suite_root_name": suite.name,
        "suite_commit": None,
        "suite_git_metadata": "unavailable in extracted P1 folder",
        "suite_package_lock_sha256": digest(suite_lock),
        "suite_tool_versions": {"react": suite_manifest.get("peerDependencies", {}).get("react"),
                                "vitest": suite_manifest.get("devDependencies", {}).get("vitest"),
                                "typescript": suite_manifest.get("devDependencies", {}).get("typescript")},
        "contract_snapshot_match": contract_matches,
        "contract_sha256": {name: reference["contracts"][name]["sha256"]
                            for name in ("suite-ui-module.v1.schema.json", "suite-chart.v1.schema.json")},
        "p4_source_sha256": {"products/p4/ui/P4Panel.tsx": digest(ROOT / "products/p4/ui/P4Panel.tsx"),
                             "products/p4/ui/P4Panel.test.tsx": digest(ROOT / "products/p4/ui/P4Panel.test.tsx")},
        "component_tests": {"return_code": component_test["return_code"], "tests_passed": tests_passed,
                            "test_file": "products/p4/ui/P4Panel.test.tsx",
                            "diagnostic": ((component_test["stdout"] + component_test["stderr"])[-4000:]
                                          if component_test["return_code"] != 0 or tests_passed != 8 else None)},
        "typecheck": {"return_code": typecheck["return_code"], "status": "PASS" if typecheck["return_code"] == 0 else "FAIL"},
        "accessibility_scope": {"native_semantic_tables": True, "labeled_keyboard_focusable_filters": True,
                                "refused_results_hide_positive_claims": True,
                                "formal_wcag": "NOT_RUN", "screen_reader": "NOT_RUN",
                                "integrated_host_focus_and_visual_tokens": "NOT_RUN"},
        "integration_status": "PENDING_P1_HOST_AND_CAPABILITY_CONTRACT_CHANGE",
    }
    output = ROOT / "release" / "UI_COMPONENT_QUALIFICATION.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "tests_passed": tests_passed,
                      "typecheck": report["typecheck"]["status"], "contract_snapshot_match": contract_matches,
                      "report": str(output)}, indent=2))
    return 0 if report["status"] == "PASS_LOCAL_MODULE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
