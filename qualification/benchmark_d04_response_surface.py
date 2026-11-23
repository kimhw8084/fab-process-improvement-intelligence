#!/usr/bin/env python3
"""Independent geometry and known-quadratic check for P4 central-composite DOE."""
from __future__ import annotations

from collections import Counter
import argparse
import json
from pathlib import Path
from itertools import product

import numpy as np
from pyDOE3 import ccdesign, ff2n

from products.p4.design import propose_design


def _terms(points: np.ndarray) -> np.ndarray:
    count, dimensions = points.shape
    columns = [np.ones(count)]
    columns.extend(points[:, index] for index in range(dimensions))
    columns.extend(points[:, index]**2 for index in range(dimensions))
    columns.extend(points[:, left]*points[:, right]
                   for left in range(dimensions) for right in range(left+1, dimensions))
    return np.column_stack(columns)


def _signature(points) -> Counter:
    return Counter(tuple(round(float(value), 10) for value in point) for point in points)


def _surface_fit_check() -> dict:
    dimensions = 3
    names = [f"x{index+1}" for index in range(dimensions)]
    proposal = propose_design("central_composite", names,
                              {name: [-1.0, 1.0] for name in names},
                              {"run_budget": 16, "blocks": 4, "center_replicates": 2,
                               "seed": 20261123}, [])
    coded = np.asarray([[run[name] for name in names] for run in proposal["runs"]], dtype=float)
    model_matrix = _terms(coded)
    beta = np.asarray([2.0, 0.4, -0.25, 0.15, 0.3, -0.18, 0.22, 0.07, -0.05, 0.09])
    response = model_matrix @ beta
    fitted, _, rank, _ = np.linalg.lstsq(model_matrix, response, rcond=None)
    evaluation = np.asarray(list(product((-1.0, -0.5, 0.0, 0.5, 1.0), repeat=dimensions)))
    truth = _terms(evaluation) @ beta
    prediction = _terms(evaluation) @ fitted
    full_factorial = ff2n(dimensions)
    return {"dimensions": dimensions,
            "central_composite_runs": int(len(coded)),
            "quadratic_parameter_count": int(model_matrix.shape[1]),
            "central_composite_matrix_rank": int(np.linalg.matrix_rank(model_matrix)),
            "full_factorial_runs": int(len(full_factorial)),
            "full_factorial_quadratic_rank": int(np.linalg.matrix_rank(_terms(full_factorial))),
            "exact_quadratic_recovery_rank": int(rank),
            "heldout_grid_points": int(len(evaluation)),
            "heldout_grid_max_abs_error": float(np.max(np.abs(prediction-truth))),
            "qualification": "noiseless known quadratic only; establishes term identifiability and exact recovery, not effect precision, power, higher-order robustness, or safe process settings"}


def run() -> dict:
    geometry = []
    for dimensions in (2, 3, 4, 5):
        names = [f"x{index+1}" for index in range(dimensions)]
        bounds = {name: [-1.0, 1.0] for name in names}
        center_count = 2
        run_count = 2**dimensions+2*dimensions+center_count
        proposal = propose_design("central_composite", names, bounds,
                                  {"run_budget": run_count, "blocks": 2,
                                   "center_replicates": center_count, "seed": 20261123}, [])
        candidate = [[run[name] for name in names] for run in proposal["runs"]]
        oracle = ccdesign(dimensions, center=(center_count, 0), face="ccf")
        p = 1+2*dimensions+dimensions*(dimensions-1)//2
        matrix = _terms(np.asarray(candidate, dtype=float))
        geometry.append({"dimensions": dimensions, "run_count": run_count,
                         "quadratic_parameter_count": p,
                         "pydoe3_ccf_geometry_exact_match": _signature(candidate) == _signature(oracle),
                         "p4_quadratic_rank": int(np.linalg.matrix_rank(matrix)),
                         "required_full_rank": p,
                         "full_factorial_rank": int(np.linalg.matrix_rank(_terms(ff2n(dimensions))))})
    return {"schema": "p4-d04-response-surface-benchmark/v1",
            "candidate": "P4 face-centered central-composite design with two independently repeated center points",
            "mature_oss_reference": "qualification-only pyDOE3.ccdesign(face='ccf', center=(2,0)); not a product dependency",
            "dimensions": geometry,
            "known_quadratic_surface": _surface_fit_check(),
            "qualification": "Independent geometry oracle and exact quadratic interpolation establish full rank/term recovery within bounds. No noisy-surface power or manufacturing feasibility is claimed; forbidden-region intersections fail closed in product code."}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
