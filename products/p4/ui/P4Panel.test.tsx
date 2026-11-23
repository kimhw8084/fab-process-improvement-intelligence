import * as React from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { P4Panel, type P4Evidence, type SourcePreview, type SuiteChartModel } from "./P4Panel";

const sourcePreview: SourcePreview = {
  status: "SYNTHETIC_ONLY", permission: "No company access configured.", semantic_version: "SYNTHETIC-NOT-APPROVED",
  grain: "one observation per independent lot", metric: "yield_index", unit: "index", scope: "held-out synthetic fixture",
  time_window: "2026-01-01 to 2026-01-31", coverage: { independent_lots: 12 },
};

const d02Grid = [
  { factors: { pressure: 2.0, temperature: 40 }, region_class: "observed", conservative_feasible: true, predictions: { yield_index: { estimate: 88.2, predictive_interval95: [87.5, 88.9], model_predictive_interval95: [87.8, 88.6], calibration_status: "LOCAL_GROUP_HOLDOUT_EMPIRICAL", calibration_units: 20, status: "ESTIMATED" } } },
  { factors: { pressure: 2.5, temperature: 42 }, region_class: "interpolated", conservative_feasible: false, predictions: { yield_index: { estimate: 87.1, predictive_interval95: [85.3, 88.9], model_predictive_interval95: [86.6, 87.6], calibration_status: "LOCAL_GROUP_HOLDOUT_EMPIRICAL", calibration_units: 20, status: "ESTIMATED" } } },
  { factors: { pressure: 4, temperature: 50 }, region_class: "unsupported", conservative_feasible: null, predictions: { yield_index: { estimate: null, predictive_interval95: null, status: "UNSUPPORTED" } } },
];

const evidence: P4Evidence = {
  status: "VALID", investigation_id: "SYN-P4-UI-01", claims: [{ statement: "Adjusted observational associations only.", category: "ASSOCIATION", certainty: "SUPPORTED", method: "cluster_robust_quadratic_ols" }],
  limitations: ["Synthetic fixture only; no company source was consulted."], assumptions: ["Lot is the independent unit."],
  sources: [{ id: "SYN-FIXTURE-p4", source_hash: "deadbeef", grain: "one row per lot and process step" }],
  provenance: { input_sha256: "deadbeef", engine_version: "p4-ui-fixture", method_version: "test" },
  artifacts: [{ type: "p4_decision_dossier", D01_sensitivity: {
    status: "VALID", interpretation: "Association is conditional on included chamber effects.",
    terms: { pressure: { estimate: 0.4, ci95: [0.1, 0.7], standard_error: 0.15 } }, diagnostics: { condition_index: 9.2, cluster_count: 12 }, diagnostic_warnings: [],
  }, D02_observed_process_window: { status: "VALID", candidate_count: 1, method: "observed_only", qualification: "Observed support only" },
  D02_robust_observed_region: { status: "VALID", count: 1, independent_unit_field: "lot_id" },
  D02_supported_region: { status: "VALID", qualification: "Supported exploration only", method: "supported_grid_response_surface_with_local_grouped_holdout_calibration",
    uncertainty_rule: "All local group-held-out empirical intervals using a 95% order-statistic rank satisfy the explicit metric limits; this does not guarantee conditional coverage.",
    calibration: { method: "local_grouped_holdout_absolute_error", coverage_guarantee: "none; local selection does not establish conditional coverage", group_field: "lot_id", training_unit_count: 30, calibration_unit_count: 20, minimum_local_calibration_units: 19, split_reference: "SYN-DO02-INTERLEAVED-001" },
    region_counts: { observed: 1, interpolated: 1, extrapolated: 0, unsupported: 1 },
    grid: d02Grid, candidate_cells: [d02Grid[0]] },
  D03_tradeoffs: { status: "VALID", qualification: "Descriptive setting means; uncertainty is shown in the table.", causal_claim: false,
    objective_metrics: [{ metric: "yield_index", direction: "maximize" }, { metric: "defect_rate", direction: "minimize" }],
    pareto_setting_ids: ["SYN-SETTING-01"], pareto_values: [{ id: "SYN-SETTING-01", yield_index: 88.2, defect_rate: 1.3 }],
    candidate_settings: [{ id: "SYN-SETTING-01", factors: { pressure: 2 }, independent_units: 12, means: { yield_index: 88.2, defect_rate: 1.3 } }],
  },
  D04_experiment_proposal: { status: "PROPOSED", run_count: 2, design: "blocked randomized factorial", executed: false,
    qualification: "Engineer review and authorization required.", authorization_fields: ["reviewer"], power: { qualification: "prospective only" },
    runs: [{ run_order: 1, block: 1, replicate: 1, pressure: 1 }, { run_order: 2, block: 1, replicate: 1, pressure: 2 }], factors: [{ name: "pressure" }],
  },
  D05_effectiveness: { status: "INCONCLUSIVE", design: "difference_in_differences", estimate: null, causal_claim: false,
    assumptions: ["Parallel trends cannot be established."], qualification: "Sensitivity result crosses zero.", diagnostics: { pretrend: "NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND" },
    sensitivity: { bounds: [-0.2, 0.3] }, attrition: { excluded: 1 },
  },
  counterevidence: [{ finding: "Negative control did not reproduce the effect." }], }],
};

const externalChart: SuiteChartModel = {
  schema_version: "suite-chart.v1", chart_id: "p4-external-fixture", kind: "line", title: "Held-out response",
  x_label: "Time", y_label: "Yield index", series: [{ id: "heldout", label: "Holdout", style: "solid" }],
  points: [{ x: "2026-01-30", values: { heldout: 88.2 } }],
};

afterEach(cleanup);

describe("P4 headless suite module", () => {
  it("shows source scope, claims, limitations, and provenance", () => {
    render(<P4Panel sourcePreview={sourcePreview} evidence={evidence} />);
    expect(screen.getByText("Synthetic demonstration data only")).toBeTruthy();
    expect(screen.getByText("one observation per independent lot")).toBeTruthy();
    expect(screen.getByText("Adjusted observational associations only.")).toBeTruthy();
    expect(screen.getByText("Synthetic fixture only; no company source was consulted.")).toBeTruthy();
    expect(screen.getAllByText("deadbeef").length).toBeGreaterThan(0);
  });

  it("renders uncertainty and model diagnostics with scientific labels", () => {
    render(<P4Panel sourcePreview={sourcePreview} evidence={evidence} />);
    const d01 = screen.getByRole("region", { name: "D01 · Factor sensitivity" });
    expect(within(d01).getByText(/estimate 0.4; 95% interval \[0.1,0.7\]; SE 0.15/)).toBeTruthy();
    expect(within(d01).getByText(/condition_index/)).toBeTruthy();
  });

  it("filters the D02 table while preserving observed, interpolated, and unsupported labels", () => {
    render(<P4Panel sourcePreview={sourcePreview} evidence={evidence} />);
    const d02 = screen.getByRole("region", { name: "D02 · Evidence-supported process window" });
    const region = within(d02).getByLabelText("Evidence region");
    fireEvent.change(region, { target: { value: "interpolated" } });
    expect(within(d02).getByRole("status").textContent).toContain("Showing 1 of 3");
    expect(within(d02).getByText("interpolated")).toBeTruthy();
    expect(within(d02).queryByText("unsupported")).toBeNull();
    fireEvent.change(region, { target: { value: "all" } });
    expect(within(d02).getByText("unsupported")).toBeTruthy();
    expect(within(d02).queryByText(/85.3,0.9/)).toBeNull();
    expect(within(d02).getByText(/85.3,88.9/)).toBeTruthy();
    expect(within(d02).getAllByText(/group-held-out empirical interval/).length).toBeGreaterThan(0);
    expect(within(d02).getAllByText(/does not guarantee conditional coverage/).length).toBeGreaterThan(0);
    expect(within(d02).getByText(/SYN-DO02-INTERLEAVED-001/)).toBeTruthy();
  });

  it("keeps native filter controls keyboard-focusable and in tab order", async () => {
    const user = userEvent.setup();
    render(<P4Panel sourcePreview={sourcePreview} evidence={evidence} />);
    const region = screen.getByLabelText("Evidence region") as HTMLSelectElement;
    region.focus();
    expect(document.activeElement).toBe(region);
    const feasibility = screen.getByLabelText("Conservative feasibility");
    await user.tab();
    expect(document.activeElement).toBe(feasibility);
  });

  it("delegates Pareto visualization to the host and keeps setting identities in an accessible table", () => {
    const renderChart = vi.fn(() => <div role="img" aria-label="Host rendered Pareto scatter" />);
    render(<P4Panel sourcePreview={sourcePreview} evidence={evidence} renderChart={renderChart} />);
    expect(renderChart).toHaveBeenCalledWith(expect.objectContaining({ schema_version: "suite-chart.v1", kind: "scatter" }));
    expect(screen.getByRole("img", { name: "Host rendered Pareto scatter" })).toBeTruthy();
    expect(screen.getByRole("rowheader", { name: "SYN-SETTING-01" })).toBeTruthy();
    expect(screen.getByText("No causal claim is made from these observed tradeoffs.")).toBeTruthy();
  });

  it("shows D04 as a non-executed proposal and withholds unsupported causal D05", () => {
    render(<P4Panel sourcePreview={sourcePreview} evidence={evidence} />);
    expect(screen.getByText(/Proposed runs: 2\. Executed: false/)).toBeTruthy();
    expect(screen.getByText(/No equipment command is issued/)).toBeTruthy();
    expect(screen.getByText("Causal interpretation is withheld; this estimate is not presented as causal.")).toBeTruthy();
    expect(screen.getByText("NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND")).toBeTruthy();
  });

  it("withholds claims, charts, and decision sections for refused evidence", () => {
    const refused: P4Evidence = { ...evidence, status: "REFUSED", claims: [{ statement: "forbidden result" }] };
    render(<P4Panel sourcePreview={sourcePreview} evidence={refused} charts={[externalChart]} />);
    expect(screen.getByText("Positive findings and charts are withheld because this result is refused.")).toBeTruthy();
    expect(screen.queryByText("forbidden result")).toBeNull();
    expect(screen.queryByRole("region", { name: "D01 · Factor sensitivity" })).toBeNull();
    expect(screen.queryByRole("img", { name: "Host rendered Pareto scatter" })).toBeNull();
  });

  it("keeps the no-result state inside the host-owned request lifecycle", () => {
    render(<P4Panel sourcePreview={sourcePreview} />);
    expect(screen.getByText("No analysis result is available. The shared workspace owns request, retry, and cancellation controls.")).toBeTruthy();
  });
});
