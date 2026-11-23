"""Recreate a clustered, nonlinear, multi-setting synthetic product walkthrough."""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
observations = []
index = 0
start = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
for lot in range(100):
    chamber = "SYN-CH-A" if lot < 50 else "SYN-CH-B"
    chamber_effect = 0.15 if lot < 50 else -0.15
    lot_effect = 0.12*math.sin(lot*0.71)
    for pressure in (1.0, 2.0, 3.0):
        for temperature in (40.0, 45.0, 50.0):
            index += 1
            noise = 0.05*math.sin(lot*1.17+pressure*0.9+temperature*0.15)
            yield_value = (80+3*pressure-0.3*(temperature-40)+0.12*(pressure-2)**2
                           +chamber_effect+lot_effect+noise)
            defect_value = (1+0.4*pressure+0.1*(temperature-40)-0.03*(pressure-2)**2
                            -0.02*chamber_effect+0.025*math.sin(lot*0.31+pressure+temperature))
            observations.append({
                "id": f"SYN-OBS-{index:04d}", "wafer_id": f"SYN-WAFER-{index:04d}",
                "lot_id": f"SYN-LOT-{lot+1:03d}", "chamber": chamber,
                "analysis_partition": "CALIBRATION" if lot % 5 < 2 else "TRAIN",
                "event_ts": (start+timedelta(minutes=index)).isoformat(),
                "factors": {"pressure": pressure, "temperature": temperature},
                "metrics": {"yield_index": round(yield_value, 5), "defect_rate": round(defect_value, 5)},
            })

request = {
    "objective": "Synthetic walkthrough: estimate lot-clustered response surfaces and inspect conservative feasible settings",
    "context": {"product": "SYN-PRODUCT", "process_step": "SYN-ETCH", "equipment": "SYN-TOOL"},
    "grain": "one synthetic wafer observation at one process instance",
    "sampling_unit": "wafer observations clustered within synthetic lots",
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
    "objectives": [{"metric": "yield_index", "direction": "maximize"},
                   {"metric": "defect_rate", "direction": "minimize"}],
    "robustness": {"min_independent_units": 15, "independent_unit_field": "lot_id"},
    "window_exploration": {"factors": ["pressure", "temperature"], "fixed_effects": {"chamber": "SYN-CH-A"},
                           "independent_unit_field": "lot_id", "min_independent_units": 15,
                           "grid_points": 15, "min_support_points": 3, "max_support_radius": 0.65,
                           "calibration": {"group_field": "lot_id", "partition_field": "analysis_partition",
                                           "training_value": "TRAIN", "calibration_value": "CALIBRATION",
                                           "minimum_calibration_units": 19,
                                           "split_reference": "SYN-P4-LOT-HOLDOUT-20PCT-INTERLEAVED-001"}},
    "model": {"covariance": "cluster", "cluster_field": "lot_id", "minimum_clusters": 30,
              "fixed_effect_fields": ["chamber"], "interactions": True, "quadratic": True},
    "experiment_design": {"strategy": "full_factorial", "run_budget": 8, "replicates": 2,
                          "blocks": 2, "seed": 20261122, "noise_sd": 1,
                          "minimum_detectable_effect": 2},
    "effectiveness": {
        "authorized": True, "authorization_id": "SYN-APPROVAL-001", "intervention_id": "SYN-CHANGE-001",
        "design": "randomized", "randomized": True, "randomization_evidence": "SYN-RANDOMIZATION-001",
        "metric": "quality_index",
        "observations": [
            {"unit_id": f"SYN-{group}-{index}", "group": group, "quality_index": value}
            for group, values in (("treatment", [89, 90, 91, 90]), ("control", [85, 86, 84, 85]))
            for index, value in enumerate(values, 1)
        ],
        "assignment_ledger": [
            {"unit_id": f"SYN-{group}-{index}", "group": group}
            for group, values in (("treatment", [89, 90, 91, 90]), ("control", [85, 86, 84, 85]))
            for index, _value in enumerate(values, 1)
        ],
    },
    "validation_split": {
        "split_type": "time", "train_timestamps": ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"],
        "test_timestamps": ["2026-01-03T00:00:00Z", "2026-01-04T00:00:00Z"],
        "train_groups": ["SYN-TRAIN-LOT-1", "SYN-TRAIN-LOT-2"], "test_groups": ["SYN-HOLDOUT-LOT-1"],
    },
    "observations": observations,
}
(ROOT/"fixtures"/"full_workflow_demo.json").write_text(json.dumps(request, indent=2, sort_keys=True)+"\n", encoding="utf-8")
print(f"Wrote {len(observations)} deterministic clustered synthetic observations across 100 lots.")
