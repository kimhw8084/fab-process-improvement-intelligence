"""Shared gates for complete synthetic D01–D05 workflow evidence."""

CAPABILITY_ARTIFACT_KEYS = {
    "D01": "D01_sensitivity",
    "D02": "D02_supported_region",
    "D03": "D03_tradeoffs",
    "D04": "D04_experiment_proposal",
    "D05": "D05_effectiveness",
}

ACCEPTABLE_CAPABILITY_STATUSES = {
    "D01": {"VALID", "INCONCLUSIVE"},
    "D02": {"VALID", "INCONCLUSIVE"},
    "D03": {"VALID", "LIMITED_SCOPE"},
    "D04": {"PROPOSED", "INCONCLUSIVE"},
    "D05": {"ESTIMATED", "INCONCLUSIVE"},
}


def capability_statuses_for_dossier(dossier):
    if not isinstance(dossier, dict) or any(key not in dossier for key in CAPABILITY_ARTIFACT_KEYS.values()):
        return {}
    statuses = {}
    for capability, key in CAPABILITY_ARTIFACT_KEYS.items():
        artifact = dossier[key]
        if not isinstance(artifact, dict):
            return {}
        statuses[capability] = artifact.get("status")
    return statuses


def capability_statuses_are_qualified(statuses):
    return (isinstance(statuses, dict)
            and set(statuses) == set(ACCEPTABLE_CAPABILITY_STATUSES)
            and all(statuses[name] in allowed for name, allowed in ACCEPTABLE_CAPABILITY_STATUSES.items()))


def analysis_result_is_qualified(result, *, expected_product_id="p4"):
    if not isinstance(result, dict) or result.get("status") not in {"VALID", "PARTIAL"}:
        return False, {}
    if result.get("product_id") != expected_product_id:
        return False, {}
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return False, {}
    statuses = capability_statuses_for_dossier(artifacts[0])
    return capability_statuses_are_qualified(statuses), statuses


def performance_record_is_qualified(performance):
    workflow = performance.get("result_checks", {}).get("integrated_full_workflow_demo_900_rows", {})
    statuses = workflow.get("capability_statuses", {})
    return (workflow.get("status") in {"VALID", "PARTIAL"}
            and workflow.get("qualification_status") == "PASS"
            and capability_statuses_are_qualified(statuses))
