"""Run P4's standalone workbench through a real local Chromium browser.

Playwright and its browser are qualification-host tools only; neither is a P4
runtime dependency. The check refuses external network requests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import threading
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fabintel.server import LocalServer  # noqa: E402
from qualification.ui_evidence import STANDALONE_SOURCE_PATHS  # noqa: E402


def _synthetic_mcp_config():
    template = json.loads((ROOT / "fixtures" / "full_workflow_demo.json").read_text(encoding="utf-8"))
    source_observations = template.pop("observations")
    template.pop("sources", None)
    template.pop("linkage", None)
    template["grain"] = "one row per synthetic process observation"
    template["sampling_unit"] = "synthetic independent lot"
    template["timestamp_semantics"] = "UTC-offset ISO-8601 event timestamp"
    for factor in template["factors"]:
        factor["unit"] = "SYNTHETIC-PRESSURE" if factor["name"] == "pressure" else "SYNTHETIC-TEMPERATURE"
    for metric in template["metrics"]:
        metric["unit"] = "SYNTHETIC-INDEX" if metric["name"] == "yield_index" else "SYNTHETIC-RATE"
    source_ids = ["SYN-SOURCE-A", "SYN-SOURCE-B"]
    time_window = {"start": "2026-01-01T00:00:00Z", "end": "2026-02-01T00:00:00Z"}
    rows = []
    for item in source_observations:
        row_id = item["id"]
        rows.append({"row_id": row_id, "unit_id": row_id, "upstream_unit_id": row_id,
            "downstream_unit_id": row_id, "event_ts": item["event_ts"],
            "upstream_event_ts": item["event_ts"], "downstream_event_ts": item["event_ts"],
            "population_id": "SYNTHETIC-POPULATION-1",
            "pressure": item["factors"]["pressure"], "temperature": item["factors"]["temperature"],
            "response_primary": item["metrics"]["yield_index"],
            "response_secondary": item["metrics"]["defect_rate"], "synthetic_value": 0.0,
            "lot_id": item["lot_id"], "wafer_id": item["wafer_id"], "chamber": item["chamber"],
            "analysis_partition": item["analysis_partition"]})
    request = {"approved_source_ids": source_ids, "semantic_version": "SYNTHETIC-SEMANTICS-1",
        "permission_scope": "SYNTHETIC_READ", "time_window": time_window,
        "approved_plan": {"source_ids": source_ids, "time_window": time_window, "synthetic_rows": rows},
        "permission_context": {"scope": "SYNTHETIC_READ", "read_only": True}, "max_rows": len(rows),
        "normalization": {"row_id_field": "row_id", "unit_field": "unit_id", "timestamp_field": "event_ts",
            "factor_fields": {"pressure": "pressure", "temperature": "temperature"},
            "metric_fields": {"yield_index": "response_primary", "defect_rate": "response_secondary"},
            "passthrough_fields": ["lot_id", "wafer_id", "chamber", "analysis_partition"]},
        "analysis_template": template}
    config = json.loads((ROOT / "requirements" / "synthetic-mcp-mapping.v1.json").read_text(encoding="utf-8"))
    config["transport"] = {"type": "stdio", "command": [sys.executable, "-m", "fabintel.mock_mcp_server"],
                           "cwd": str(ROOT), "timeout_seconds": 5}
    config["p4_profile"] = {key: request[key] for key in (
        "semantic_version", "permission_scope", "time_window", "approved_plan", "permission_context",
        "max_rows", "normalization", "analysis_template")}
    return config


def qualify():
    from playwright.sync_api import sync_playwright

    source_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                     for name in STANDALONE_SOURCE_PATHS}
    source_commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                                   text=True, capture_output=True).stdout.strip()
    servers = [LocalServer(0), LocalServer(0, mcp_config=_synthetic_mcp_config(),
                                          allow_synthetic_mcp_test=True)]
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    request_urls, page_errors, failed_responses = [], [], []
    result = {"schema": "p4-standalone-ui-browser/v1", "status": "FAIL",
              "source_commit": source_commit, "source_sha256": source_hashes,
              "browser": None, "checks": {}, "external_requests": [], "page_errors": [],
              "failed_responses": [], "scope": "P4 standalone local application only; no P1 or other product host"}
    try:
        with sync_playwright() as playwright:
            options = {"headless": True}
            system_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            if system_chrome.is_file():
                options["executable_path"] = str(system_chrome)
            browser = playwright.chromium.launch(**options)
            result["browser"] = browser.version
            page = browser.new_page(accept_downloads=True)
            page.on("request", lambda request: request_urls.append(request.url))
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on("response", lambda response: failed_responses.append(
                {"url": response.url, "status": response.status}) if response.status >= 400 else None)
            base = f"http://127.0.0.1:{servers[0].server_port}"
            mcp_base = f"http://127.0.0.1:{servers[1].server_port}"
            allowed_bases = (base, mcp_base)
            page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(allowed_bases)
                       else route.abort())
            page.goto(base, wait_until="networkidle", timeout=10000)
            page.keyboard.press("Tab")
            skip_focused = page.locator(".skip-link").evaluate("el => el === document.activeElement")
            page.keyboard.press("Tab")
            demo_focused = page.locator("#load-demo").evaluate("el => el === document.activeElement")
            page.keyboard.press("Enter")
            deadline = time.monotonic() + 5
            while not page.locator("#run-analysis").is_enabled() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not page.locator("#run-analysis").is_enabled():
                raise AssertionError("loading the synthetic example did not enable analysis")
            page.locator("#run-analysis").focus()
            page.keyboard.press("Enter")
            page.locator("#results").wait_for(state="visible", timeout=15000)
            capabilities = page.locator("#capability-results").inner_text()
            headings = {name: page.get_by_role("heading", name=name).count() > 0 for name in
                        ("D01 · Factor sensitivity", "D02 · Supported process region",
                         "D03 · Objective tradeoffs", "D04 · Next experiment",
                         "D05 · Intervention evaluation")}
            table_count = page.locator("#visuals table").count()
            mcp_disabled_without_config = (
                page.locator("#run-mcp").is_disabled()
                and page.locator("#mcp-state").inner_text() == "NOT_CONFIGURED")
            lazy_pre = page.locator(".capability-evidence pre")
            evidence_lazy_before_open = all(not (lazy_pre.nth(i).text_content() or "")
                                            for i in range(lazy_pre.count()))
            page.locator(".capability-evidence summary").first.click()
            deadline = time.monotonic() + 5
            while not (page.locator(".capability-evidence pre").first.text_content() or "") and time.monotonic() < deadline:
                time.sleep(0.05)
            capability_evidence_opens = len(page.locator(".capability-evidence pre").first.text_content() or "") > 0
            page.locator("details.raw-evidence summary").click()
            deadline = time.monotonic() + 5
            while not (page.locator("#raw-json").text_content() or "") and time.monotonic() < deadline:
                time.sleep(0.05)
            raw_evidence_opens = len(page.locator("#raw-json").text_content() or "") > 0
            with page.expect_download(timeout=5000) as download_info:
                page.locator("#export-result").click()
            download = download_info.value
            exported_path = download.path()
            exported = json.loads(Path(exported_path).read_text(encoding="utf-8"))
            mcp_page = browser.new_page(accept_downloads=True)
            mcp_page.on("request", lambda request: request_urls.append(request.url))
            mcp_page.on("pageerror", lambda error: page_errors.append(str(error)))
            mcp_page.on("response", lambda response: failed_responses.append(
                {"url": response.url, "status": response.status}) if response.status >= 400 else None)
            mcp_page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(allowed_bases)
                           else route.abort())
            mcp_page.goto(mcp_base, wait_until="networkidle", timeout=10000)
            mcp_status = mcp_page.evaluate("fetch('/api/mcp/status').then(response => response.json())")
            mcp_page.locator("#run-mcp").wait_for(state="visible")
            deadline = time.monotonic() + 5
            while mcp_page.locator("#run-mcp").is_disabled() and time.monotonic() < deadline:
                time.sleep(0.05)
            if mcp_page.locator("#run-mcp").is_disabled():
                raise AssertionError("configured synthetic MCP acquisition did not enable the standalone UI action")
            mcp_page.locator("#run-mcp").focus()
            mcp_page.keyboard.press("Enter")
            deadline = time.monotonic() + 30
            while not mcp_page.locator("#results").is_visible() and time.monotonic() < deadline:
                time.sleep(0.1)
            if not mcp_page.locator("#results").is_visible():
                raise AssertionError("configured MCP workflow did not render evidence; "
                                     f"UI status={mcp_page.locator('#run-status').inner_text()!r}; "
                                     f"failed responses={failed_responses!r}")
            mcp_page.locator("details.raw-evidence summary").click()
            deadline = time.monotonic() + 5
            while not (mcp_page.locator("#raw-json").text_content() or "") and time.monotonic() < deadline:
                time.sleep(0.05)
            with mcp_page.expect_download(timeout=5000) as mcp_download_info:
                mcp_page.locator("#export-result").click()
            mcp_export = json.loads(Path(mcp_download_info.value.path()).read_text(encoding="utf-8"))
            acquisition = mcp_export.get("provenance", {}).get("mcp_acquisition", {})
            dossier = (mcp_export.get("artifacts") or [{}])[0]
            capability_statuses = {
                "D01_sensitivity": {"VALID"},
                "D02_supported_region": {"VALID", "INCONCLUSIVE"},
                "D03_tradeoffs": {"VALID", "LIMITED_SCOPE"},
                "D04_experiment_proposal": {"PROPOSED"},
                "D05_effectiveness": {"ESTIMATED"},
            }
            result["checks"] = {
                "keyboard_skip_link": bool(skip_focused),
                "keyboard_demo_activation": bool(demo_focused),
                "keyboard_analysis_activation": True,
                "all_d01_d05_headings": all(headings.values()),
                "d01_d05_headings": headings,
                "accessible_table_alternative_present": table_count > 0,
                "table_alternative_count": table_count,
                "capability_evidence_lazy_until_requested": evidence_lazy_before_open,
                "capability_evidence_opens_on_request": capability_evidence_opens,
                "full_evidence_opens_on_request": raw_evidence_opens,
                "evidence_export_downloaded": bool(exported.get("product_id") == "p4"),
                "advisory_text_visible": "not a production guarantee" in page.locator("#results").inner_text().lower(),
                "capability_results_text_length": len(capabilities),
                "mcp_disabled_without_config": mcp_disabled_without_config,
                "configured_mcp_status_pending_internal": (
                    mcp_status.get("qualification_status") == "PENDING_INTERNAL"
                    and mcp_status.get("environment") == "SYNTHETIC_TEST_ONLY"),
                "configured_mcp_acquisition_completed": (
                    mcp_export.get("product_id") == "p4"
                    and acquisition.get("status") == "ANALYSIS_COMPLETED"
                    and acquisition.get("row_count") == 900
                    and acquisition.get("read_only") is True),
                "configured_mcp_audit_receipt_present": (
                    bool(acquisition.get("audit_id")) and bool(acquisition.get("operation_id"))
                    and bool(acquisition.get("audit_query_hash"))),
                "configured_mcp_all_capabilities_present": all(
                    dossier.get(name, {}).get("status") in accepted
                    for name, accepted in capability_statuses.items()),
                "configured_mcp_evidence_exported": bool(mcp_export.get("provenance", {}).get("mcp_acquisition")),
            }
            mcp_page.close()
            browser.close()
        result["external_requests"] = [url for url in request_urls if not url.startswith(allowed_bases)]
        result["page_errors"] = page_errors
        result["failed_responses"] = failed_responses
        checks = result["checks"]
        if (checks.get("keyboard_skip_link") and checks.get("keyboard_demo_activation")
                and checks.get("keyboard_analysis_activation") and checks.get("all_d01_d05_headings")
                and checks.get("accessible_table_alternative_present")
                and checks.get("capability_evidence_lazy_until_requested")
                and checks.get("capability_evidence_opens_on_request")
                and checks.get("full_evidence_opens_on_request")
                and checks.get("evidence_export_downloaded") and checks.get("advisory_text_visible")
                and checks.get("configured_mcp_status_pending_internal")
                and checks.get("configured_mcp_acquisition_completed")
                and checks.get("configured_mcp_audit_receipt_present")
                and checks.get("configured_mcp_all_capabilities_present")
                and checks.get("configured_mcp_evidence_exported")
                and not result["external_requests"] and not page_errors and not failed_responses):
            result["status"] = "PASS_STANDALONE_INTERACTION_LIMITED_SCOPE"
        result["accessibility_scope"] = {
            "keyboard_workflow": "checked",
            "native_headings_status_and_table_alternative": "checked",
            "screen_reader_and_formal_wcag_audit": "not performed",
        }
        result["qualified_at_utc"] = datetime.now(timezone.utc).isoformat()
        return result
    finally:
        for server in servers:
            server.jobs.stop_all()
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="release/P4_STANDALONE_UI_BROWSER.json")
    args = parser.parse_args()
    report = qualify()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "evidence": args.output,
                      "checks": report.get("checks", {})}, sort_keys=True))
    return 0 if report["status"] == "PASS_STANDALONE_INTERACTION_LIMITED_SCOPE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
