"""Independent coverage challenge for calibration-selected setting panels.

Every candidate setting has the same standard-normal residual law. A target
panel must be fixed before calibration is inspected. Selecting a one-setting
panel by the smallest observed calibration radius is intentionally adaptive
and should under-cover; a max score over the predeclared complete panel should
retain its finite-sample marginal simultaneous target under exchangeability.
"""
from __future__ import annotations

import argparse
from math import ceil, sqrt
import json
import random
from pathlib import Path


def _wilson(successes: int, trials: int):
    z = 1.959963984540054
    rate = successes / trials
    denominator = 1 + z*z/trials
    center = (rate + z*z/(2*trials)) / denominator
    half = z*sqrt((rate*(1-rate) + z*z/(4*trials))/trials) / denominator
    return [max(0.0, center-half), min(1.0, center+half)]


def run_benchmark(trials: int = 5000, seed: int = 73192, calibration_units: int = 39, settings: int = 25):
    if trials < 1000 or calibration_units < 19 or settings < 2:
        raise ValueError("benchmark requires at least 1,000 trials, 19 units, and 2 settings")
    rng = random.Random(seed)
    rank = ceil((calibration_units + 1) * 0.95)
    if rank > calibration_units:
        raise ValueError("finite-sample 95% rank unavailable")
    counts = {"fixed_one_setting": 0, "adaptively_selected_one_setting": 0,
              "predeclared_complete_panel": 0}
    radii = {name: [] for name in counts}
    for _ in range(trials):
        calibration = [[abs(rng.gauss(0, 1)) for _ in range(calibration_units)]
                       for _ in range(settings)]
        setting_radii = [sorted(scores)[rank-1] for scores in calibration]
        chosen = min(range(settings), key=lambda index: (setting_radii[index], index))
        future = [abs(rng.gauss(0, 1)) for _ in range(settings)]
        panel_radius = sorted(max(calibration[setting][unit] for setting in range(settings))
                              for unit in range(calibration_units))[rank-1]
        events = {
            "fixed_one_setting": future[0] <= setting_radii[0],
            "adaptively_selected_one_setting": future[chosen] <= setting_radii[chosen],
            "predeclared_complete_panel": max(future) <= panel_radius,
        }
        for name, covered in events.items():
            counts[name] += int(covered)
        for name, radius in (("fixed_one_setting", setting_radii[0]),
                             ("adaptively_selected_one_setting", setting_radii[chosen]),
                             ("predeclared_complete_panel", panel_radius)):
            radii[name].append(radius)

    results = {name: {"covered": count, "coverage": count/trials,
                      "wilson95": _wilson(count, trials), "mean_radius": sum(radii[name])/trials}
               for name, count in counts.items()}
    return {
        "schema": "p4-d02-adaptive-selection-benchmark/v1",
        "method": "independent absolute-normal residual simulation with split-conformal rank ceil((n+1)*0.95)",
        "generator": "iid standard-normal residuals at every candidate setting; future units independent of calibration",
        "seed": seed,
        "trials": trials,
        "calibration_units": calibration_units,
        "candidate_settings": settings,
        "order_statistic_rank": rank,
        "target_coverage": 0.95,
        "results": results,
        "limitations": [
            "this isolates adaptive panel-selection bias under a known iid generator",
            "it does not establish exchangeability or coverage for manufacturing populations",
            "the predeclared complete-panel method is more conservative and covers only its finite declared panel",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=73192)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.trials, args.seed)
    fixed = result["results"]["fixed_one_setting"]["coverage"]
    adaptive = result["results"]["adaptively_selected_one_setting"]["coverage"]
    panel = result["results"]["predeclared_complete_panel"]["coverage"]
    if not 0.93 <= fixed <= 0.97 or adaptive >= 0.90 or not 0.93 <= panel <= 0.97:
        raise SystemExit("adaptive-selection benchmark did not reproduce its prespecified coverage challenge")
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
