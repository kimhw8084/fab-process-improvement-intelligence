"""Source-bound checks for the independent P4 standalone browser workflow."""

STANDALONE_SOURCE_PATHS = (
    "fabintel/server.py",
    "fabintel/mcp_client.py",
    "fabintel/site_config.py",
    "fabintel/mock_mcp_server.py",
    "products/p4/engine.py",
    "products/p4/mcp_workflow.py",
    "products/p4/ui/standalone/index.html",
    "products/p4/ui/standalone/app.js",
    "products/p4/ui/standalone/styles.css",
    "products/p4/ui/standalone/mcp.css",
    "fixtures/full_workflow_demo.json",
    "requirements/synthetic-mcp-mapping.v1.json",
    "qualification/ui_evidence.py",
    "qualification/standalone_ui_browser.py",
)

REQUIRED_STANDALONE_CHECKS = (
    "keyboard_skip_link",
    "keyboard_demo_activation",
    "keyboard_analysis_activation",
    "all_d01_d05_headings",
    "accessible_table_alternative_present",
    "capability_evidence_lazy_until_requested",
    "capability_evidence_opens_on_request",
    "full_evidence_opens_on_request",
    "evidence_export_downloaded",
    "advisory_text_visible",
    "mcp_disabled_without_config",
    "configured_mcp_status_pending_internal",
    "configured_mcp_acquisition_completed",
    "configured_mcp_audit_receipt_present",
    "configured_mcp_all_capabilities_present",
    "configured_mcp_evidence_exported",
)


def standalone_ui_evidence_matches(report, source_commit, source_sha256):
    """Accept only current-source, local-only evidence for the complete P4 UI path."""
    if not isinstance(report, dict) or not isinstance(source_sha256, dict):
        return False
    checks = report.get("checks")
    accessibility_scope = report.get("accessibility_scope")
    return (
        report.get("schema") == "p4-standalone-ui-browser/v1"
        and report.get("status") == "PASS_STANDALONE_INTERACTION_LIMITED_SCOPE"
        and report.get("source_commit") == source_commit
        and report.get("source_sha256") == source_sha256
        and bool(report.get("browser"))
        and isinstance(checks, dict)
        and all(checks.get(name) is True for name in REQUIRED_STANDALONE_CHECKS)
        and report.get("external_requests") == []
        and report.get("page_errors") == []
        and report.get("failed_responses") == []
        and isinstance(accessibility_scope, dict)
        and accessibility_scope.get("keyboard_workflow") == "checked"
        and accessibility_scope.get("screen_reader_and_formal_wcag_audit") == "not performed"
        and report.get("scope") == "P4 standalone local application only; no P1 or other product host"
    )
