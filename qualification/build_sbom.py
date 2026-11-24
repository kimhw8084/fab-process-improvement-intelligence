"""Generate a local SPDX inventory for P4 and its optional offline MCP SDK."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
product = json.loads((ROOT / "product.json").read_text(encoding="utf-8"))
root_package = {
    "name": "FAB Process Improvement Intelligence P4 Candidate",
    "SPDXID": "SPDXRef-P4-Candidate",
    "versionInfo": "1.0.0",
    "downloadLocation": "NOASSERTION",
    "filesAnalyzed": False,
    "licenseConcluded": "NOASSERTION",
    "licenseDeclared": "NOASSERTION",
    "copyrightText": "NOASSERTION",
    "primaryPackagePurpose": "APPLICATION",
    "comment": "No project license or ownership evidence is supplied; redistribution rights remain pending review.",
}
packages = [root_package]
relationships = []
annotations = [
    {"annotationType": "OTHER", "annotator": "Tool: FabIntel P4 local SBOM generator 1.0.0",
     "annotationDate": "2026-11-24T00:00:00Z",
     "comment": "Scientific core, CLI, and P4 standalone HTML/CSS/JavaScript/SVG workbench use Python/browser standard capabilities; P4 has no P1/P2/P3 runtime dependency and bundles no React, ECharts, Plotly, Cytoscape, or AG Grid runtime."},
]

golden = {
    "name": "Golden Agentic Engineering reusable-method snapshot",
    "SPDXID": "SPDXRef-Golden-Agentic-Engineering",
    "versionInfo": "0.1.0-dev+dc2ece864b2d744e47dfe8c7d9ad78aadbed369e",
    "downloadLocation": "https://github.com/kimhw8084/golden-agentic-engineering/tree/dc2ece864b2d744e47dfe8c7d9ad78aadbed369e",
    "filesAnalyzed": False,
    "licenseConcluded": "MIT",
    "licenseDeclared": "MIT",
    "copyrightText": "NOASSERTION",
    "primaryPackagePurpose": "LIBRARY",
    "comment": "Selected development-method references only; upstream qualification state is PRE_QUALIFICATION. Exact source file hashes are recorded in research/golden-agentic-engineering/SOURCE_MANIFEST.json.",
}
packages.append(golden)
relationships.append({"spdxElementId": "SPDXRef-P4-Candidate", "relationshipType": "CONTAINS",
                      "relatedSpdxElement": "SPDXRef-Golden-Agentic-Engineering"})

vendor_root = ROOT / "vendor" / "mcp-sdk" / "2.3.0" / "macos-arm64-cp311"
inventory = json.loads((vendor_root / "license-inventory.json").read_text(encoding="utf-8"))
for item in inventory["packages"]:
    identifier = "SPDXRef-MCP-" + re.sub(r"[^A-Za-z0-9.-]", "-", f"{item['name']}-{item['version']}")
    source = next((ref["url"] for ref in item.get("source_references", []) if ref.get("label") == "Source"), "NOASSERTION")
    expression = item.get("license_expression") or "NOASSERTION"
    packages.append({
        "name": item["name"], "SPDXID": identifier, "versionInfo": item["version"],
        "downloadLocation": source, "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION", "licenseDeclared": expression,
        "copyrightText": "NOASSERTION", "primaryPackagePurpose": "LIBRARY",
        "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                           "referenceLocator": f"pkg:pypi/{item['normalized_name']}@{item['version']}"}],
        "checksums": [{"algorithm": "SHA256", "checksumValue": item["wheel_sha256"]}],
        "comment": (f"Optional MCP SDK candidate dependency; target macOS ARM64 CPython 3.11. "
                    f"Wheel and embedded license-file hashes are in vendor/mcp-sdk/2.3.0/macos-arm64-cp311/license-inventory.json. "
                    f"Declared license expression from wheel metadata: {expression}. Company/legal license approval is pending."),
    })
    relationships.append({"spdxElementId": identifier, "relationshipType": "OPTIONAL_DEPENDENCY_OF",
                          "relatedSpdxElement": "SPDXRef-P4-Candidate"})

qualification_inventory = json.loads((ROOT / "release" / "QUALIFICATION_DEPENDENCY_LICENSE_INVENTORY.json").read_text(encoding="utf-8"))
for item in qualification_inventory["packages"]:
    identifier = "SPDXRef-QUAL-" + re.sub(r"[^A-Za-z0-9.-]", "-", f"{item['name']}-{item['version']}")
    declared = item.get("spdx_expression") or "NOASSERTION"
    raw_metadata = {"license": item.get("raw_license_metadata"), "classifiers": item.get("license_classifiers")}
    packages.append({
        "name": item["name"], "SPDXID": identifier, "versionInfo": item["version"],
        "downloadLocation": "NOASSERTION", "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION", "licenseDeclared": declared,
        "copyrightText": "NOASSERTION", "primaryPackagePurpose": "LIBRARY",
        "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                           "referenceLocator": item["purl"]}],
        "comment": ("Qualification/reference-only dependency; not bundled and not a P4 runtime dependency. "
                    f"Raw metadata: {json.dumps(raw_metadata, sort_keys=True)}. License file hashes are in "
                    "release/QUALIFICATION_DEPENDENCY_LICENSE_INVENTORY.json; legal interpretation remains pending."),
    })
    relationships.append({"spdxElementId": identifier, "relationshipType": "TEST_DEPENDENCY_OF",
                          "relatedSpdxElement": "SPDXRef-P4-Candidate"})

sbom = {
    "spdxVersion": "SPDX-2.3",
    "dataLicense": "CC0-1.0",
    "SPDXID": "SPDXRef-DOCUMENT",
    "name": "fab-intelligence-p4-candidate",
    "documentNamespace": "https://fabintel.invalid/spdx/p4-candidate-1.0.0",
    "creationInfo": {"creators": ["Tool: FabIntel P4 local SBOM generator 1.0.0"], "created": "2026-11-24T00:00:00Z"},
    "packages": packages,
    "relationships": relationships,
    "annotations": annotations,
}
(ROOT / "release" / "SBOM.spdx.json").write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"Wrote SPDX with {len(packages)} packages; P4 license is NOASSERTION and MCP dependencies are optional candidates.")
