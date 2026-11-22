"""Recreate the bundled synthetic end-to-end request; never uses company data."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
noise = (-0.4, 0.0, 0.4)
defect_noise = (-0.1, 0.0, 0.1)
observations = []
index = 0
for pressure in (1.0, 2.0, 3.0):
    for temperature in (40.0, 50.0):
        for replicate in range(3):
            index += 1
            observations.append({
                "id": f"SYN-OBS-{index:03d}",
                "wafer_id": f"SYN-WAFER-{index:03d}",
                "lot_id": f"SYN-LOT-{index // 4 + 1:02d}",
                "event_ts": f"2026-01-{index:02d}T12:00:00+00:00",
                "factors": {"pressure": pressure, "temperature": temperature},
                "metrics": {
                    "yield_index": round(80 + 3 * pressure - 0.3 * (temperature - 40) + noise[replicate], 3),
                    "defect_rate": round(1 + 0.4 * pressure + 0.1 * (temperature - 40) + defect_noise[replicate], 3),
                },
            })

request = {
    "objective": "Synthetic walkthrough: examine observed yield and defect tradeoffs under approved demo bounds",
    "context": {"product": "SYN-PRODUCT", "process_step": "SYN-ETCH", "equipment": "SYN-TOOL"},
    "grain": "one synthetic wafer observation at one process instance",
    "sampling_unit": "synthetic wafer",
    "timestamp_semantics": "UTC ISO-8601 fixture timestamps",
    "constraints_approved": True,
    "factors": [
        {"name": "pressure", "role": "controllable", "unit": "synthetic pressure unit", "bounds": [1, 3], "approved": True},
        {"name": "temperature", "role": "controllable", "unit": "synthetic temperature unit", "bounds": [40, 50], "approved": True},
    ],
    "metrics": [
        {"name": "yield_index", "unit": "synthetic index", "direction": "maximize", "min": 85},
        {"name": "defect_rate", "unit": "synthetic rate", "direction": "minimize", "max": 2.8},
    ],
    "primary_metric": "yield_index",
    "objectives": [
        {"metric": "yield_index", "direction": "maximize"},
        {"metric": "defect_rate", "direction": "minimize"},
    ],
    "robustness": {"min_independent_units": 3, "independent_unit_field": "wafer_id"},
    "model": {"interactions": True, "quadratic": False},
    "experiment_design": {"run_budget": 8, "replicates": 2, "blocks": 2, "seed": 20261122,
                          "noise_sd": 1, "minimum_detectable_effect": 2},
    "effectiveness": {
        "authorized": True, "authorization_id": "SYN-APPROVAL-001", "intervention_id": "SYN-CHANGE-001",
        "design": "randomized", "randomized": True, "randomization_evidence": "SYN-RANDOMIZATION-001",
        "metric": "quality_index", "observations": [
            {"unit_id": "SYN-T-1", "group": "treatment", "quality_index": 89},
            {"unit_id": "SYN-T-2", "group": "treatment", "quality_index": 90},
            {"unit_id": "SYN-T-3", "group": "treatment", "quality_index": 91},
            {"unit_id": "SYN-T-4", "group": "treatment", "quality_index": 90},
            {"unit_id": "SYN-C-1", "group": "control", "quality_index": 85},
            {"unit_id": "SYN-C-2", "group": "control", "quality_index": 86},
            {"unit_id": "SYN-C-3", "group": "control", "quality_index": 84},
            {"unit_id": "SYN-C-4", "group": "control", "quality_index": 85},
        ],
    },
    "validation_split": {
        "split_type": "time", "train_timestamps": ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"],
        "test_timestamps": ["2026-01-03T00:00:00Z", "2026-01-04T00:00:00Z"],
        "train_groups": ["SYN-TRAIN-LOT-1", "SYN-TRAIN-LOT-2"],
        "test_groups": ["SYN-HOLDOUT-LOT-1"],
    },
    "observations": observations,
}
(ROOT / "fixtures" / "full_workflow_demo.json").write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"Wrote {len(observations)} deterministic synthetic observations.")
