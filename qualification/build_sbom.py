"""Generate the package-level SPDX inventory without network access."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
product = json.loads((ROOT / "product.json").read_text(encoding="utf-8"))
sbom = {
    "spdxVersion": "SPDX-2.3",
    "dataLicense": "CC0-1.0",
    "SPDXID": "SPDXRef-DOCUMENT",
    "name": "fab-intelligence-p4-candidate",
    "documentNamespace": "https://fabintel.invalid/spdx/p4-candidate-1.0.0",
    "creationInfo": {"creators": ["Tool: FabIntel P4 local SBOM generator 1.0.0"], "created": "2026-11-22T00:00:00Z"},
    "packages": [{
        "name": "FAB Process Improvement Intelligence P4 Candidate",
        "SPDXID": "SPDXRef-P4-Candidate",
        "versionInfo": "1.0.0",
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "copyrightText": "NOASSERTION",
        "primaryPackagePurpose": "APPLICATION",
        "comment": "No project license is declared in the supplied folder; distribution rights remain pending owner review."
    }],
    "relationships": [],
    "annotations": [{"annotationType": "OTHER", "annotator": "Tool: FabIntel P4 local SBOM generator 1.0.0",
                     "annotationDate": "2026-11-22T00:00:00Z",
                     "comment": "Product runtime has no bundled third-party package dependencies. Python 3.10+ standard library is provided by the separately installed interpreter. Optional qualification dependencies are enumerated in qualification/benchmark-requirements.txt, audited in release/DEPENDENCY_AUDIT.json, and are not packaged or imported by product runtime."}],
}
(ROOT / "release" / "SBOM.spdx.json").write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("Wrote package-level SPDX; project license is NOASSERTION and no third-party runtime packages are bundled.")
