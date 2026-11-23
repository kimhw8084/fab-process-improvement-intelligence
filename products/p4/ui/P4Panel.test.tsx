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
  { factors: { pressure: 2.0, temperature: 40 }, region_class: "observed", conservative_feasible: true, simultaneous_supported_candidate: true, predictions: { yield_index: { estimate: 88.2, predictive_interval95: [87.5, 88.9], simultaneous_group_interval95: [87.2, 89.2], simultaneous_group_calibration_status: "AVAILABLE_UNDER_UNVERIFIED_EXCHANGEABILITY_ASSUMPTIONS", model_predictive_interval95: [87.8, 88.6], calibration_status: "LOCAL_GROUP_HOLDOUT_EMPIRICAL", calibration_units: 20, status: "ESTIMATED" } } },
  { factors: { pressure: 2.5, temperature: 42 }, region_class: "interpolated", conservative_feasible: false, simultaneous_supported_candidate: false, predictions: { yield_index: { estimate: 87.1, predictive_interval95: [85.3, 88.9], simultaneous_group_interval95: null, simultaneous_group_calibration_status: "NOT_IN_COMPLETE_EXACT_SETTING_PANEL", model_predictive_interval95: [86.6, 87.6], calibration_status: "LOCAL_GROUP_HOLDOUT_EMPIRICAL", calibration_units: 20, status: "ESTIMATED" } } },
  { factors: { pressure: 4, temperature: 50 }, region_class: "unsupported", conservative_feasible: null, simultaneous_supported_candidate: false, predictions: { yield_index: { estimate: null, predictive_interval95: null, simultaneous_group_interval95: null, status: "UNSUPPORTED" } } },
];

const evidence: P4Evidence = {
  status: "VALID", investigation_id: "SYN-P4-UI-01", claims: [{ statement: "Adjusted observational associations only.", category: "ASSOCIATION", certainty: "SUPPORTED", method: "cluster_robust_quadratic_ols" }],
  limitations: ["Synthetic fixture only; no company source was consulted."], assumptions: ["Lot is the independent unit."],
  sources: [{ id: "SYN-FIXTURE-p4", source_hash: "deadbeef", grain: "one row per lot and process step" }],
  provenance: { input_sha256: "deadbeef", engine_version: "p4-ui-fixture", method_version: "test" },
  artifacts: [{ type: "p4_decision_dossier", D01_sensitivity: {
    status: "VALID", interpretation: "Association is conditional on included chamber effects.",
    terms: { pressure: { estimate: 0.4, ci95: [0.1, 0.7], standard_error: 0.15 } },
    inference: { covariance: "cluster", declared_independent_unit_field: "lot_id", cluster_nesting: { status: "NESTED", clusters: 12 } },
    diagnostics: { condition_index: 9.2, cluster_count: 12 }, diagnostic_warnings: [],
    formula_sensitivity: { status: "COMPLETED_DIAGNOSTIC", factor_stability: { pressure: { sign_reversal_observed: true } } },
  }, D02_observed_process_window: { status: "VALID", candidate_count: 1, method: "observed_only", qualification: "Observed support only" },
  D02_robust_observed_region: { status: "VALID", count: 1, independent_unit_field: "lot_id" },
  validation_split: { status: "COMPLETED_DIAGNOSTIC", training_group_count: 80, test_group_count: 20,
    heldout_performance: { mae: 0.3, rmse: 0.4, rmse_skill_vs_training_mean: 0.6 },
    generalization_claim: "Descriptive holdout only." },
  D02_supported_region: { status: "VALID", qualification: "Supported exploration only", method: "supported_grid_response_surface_with_local_grouped_holdout_calibration",
    candidate_scope: "ADVISORY_POINTWISE_SCREENING_ONLY", joint_validation_status: "NOT_ESTABLISHED",
    selection_warning: "Selection among cells can inflate false-feasible findings; simultaneous coverage is not established.",
    data_roles: { model_fitting: "TRAIN", model_selection: "NOT_PERFORMED_BY_ENGINE", threshold_selection: "PRESPECIFIED" },
    uncertainty_scope: { formal_coverage_claim: "NONE_ESTABLISHED", simultaneous_coverage_over_searched_grid: "NOT_ESTABLISHED" },
    simultaneous_exact_setting_screen: { status: "AVAILABLE", status_scope: "ASSUMPTION_CONDITIONAL_EXACT_SETTING_PANEL_ONLY", calibration_unit_count: 20, familywise_alpha: 0.05, scope: "one future independent unit across a finite exact-setting panel", limitations: ["no interpolation coverage", "exchangeability unverified"] },
    uncertainty_rule: "All local group-held-out empirical intervals using a 95% order-statistic rank satisfy the explicit metric limits; this does not guarantee conditional coverage.",
    calibration: { method: "local_grouped_holdout_absolute_error", coverage_guarantee: "none; local selection does not establish conditional coverage", group_field: "lot_id", training_unit_count: 30, calibration_unit_count: 20, minimum_local_calibration_units: 19, split_reference: "SYN-DO02-INTERLEAVED-001" },
    independent_candidate_evaluation: { status: "DESCRIPTIVE", evaluated_candidate_count: 1, unevaluated_candidate_count: 0, method: "No population or simultaneous guarantee.",
      candidates: [{ factors: { pressure: 2.0, temperature: 40 }, status: "NO_EXACT_SETTING_EVALUATION_DATA", independent_units: 0,
        population_incompatible_units: 12, observed_infeasible_units: null, observed_infeasible_fraction: null,
        wilson95_descriptive_interval: null, stratified_evaluation: { status: "NOT_ESTIMABLE", categories: [] } }],
      candidate_selection_audit: { status: "INSUFFICIENT_COMPLETE_SET_EVALUATION", candidate_count: 1,
        complete_independent_units: 0, observed_any_infeasible_units: null,
        guarantee: "none; descriptive only and not a multiplicity-adjusted or population guarantee" } },
    region_counts: { observed: 1, interpolated: 1, extrapolated: 0, unsupported: 1 },
    grid: d02Grid, candidate_cells: [d02Grid[0]] },
  D03_tradeoffs: { status: "VALID", qualification: "Descriptive setting means; uncertainty is shown in the table.", causal_claim: false,
    pareto_status_scope: "mean-based observed front; marginal interval separation is diagnostic only and is not multiplicity-adjusted",
    familywise_mean_envelope: { status: "AVAILABLE_APPROXIMATE_BONFERRONI_ENVELOPE", familywise_confidence_target: 0.95, mean_parameter_count: 2 },
    objective_metrics: [{ metric: "yield_index", direction: "maximize" }, { metric: "defect_rate", direction: "minimize" }],
    pareto_setting_ids: ["SYN-SETTING-01"], pareto_values: [{ id: "SYN-SETTING-01", yield_index: 88.2, defect_rate: 1.3 }],
    candidate_settings: [{ id: "SYN-SETTING-01", factors: { pressure: 2 }, independent_units: 12,
      means: { yield_index: 88.2, defect_rate: 1.3 },
      uncertainty: { yield_index: { marginal_ci95: [87.9, 88.5], familywise_ci95: [87.7, 88.7] },
        defect_rate: { marginal_ci95: [1.1, 1.5], familywise_ci95: [1.0, 1.6] } },
      mean_pareto_status: "NONDOMINATED_BY_MEANS", uncertainty_dominance_status: "NO_INTERVAL_SEPARATED_DOMINATOR",
      familywise_dominance_status: "NO_FAMILYWISE_INTERVAL_SEPARATED_DOMINATOR", familywise_dominated_by: [] }],
  },
  D04_experiment_proposal: { status: "PROPOSED", run_count: 2, design: "randomized blocked D02 candidate confirmation", executed: false,
    qualification: "Engineer review and authorization required.", authorization_fields: ["reviewer"], power: {
      qualification: "prospective only", paired_difference_sd_basis: "ONE_SIDED_CHI_SQUARE_UPPER_CONFIDENCE_BOUND",
      paired_difference_sd_confidence_level: 0.95, paired_difference_sd_degrees_of_freedom: 29,
      paired_sd_scope: "caller-supplied conservative upper bound; P4 does not recompute or authenticate it" },
    objective_statement: "Confirm the candidate versus an engineer-supplied reference.",
    objective: { metric: "yield_index", unit: "index", direction: "maximize", minimum_detectable_effect: 1.0 },
    candidate_evidence: { region_class: "observed", simultaneous_supported_candidate: false, target_metric_interval95: [87.5, 88.9] },
    constraint_evaluation: { status: "MODEL_BASED_INTERVAL_SCREEN_ONLY", constraint_metrics: ["defect_rate"], qualification: "No feasibility guarantee." },
    runs: [{ run_order: 1, block: 1, arm: "candidate", order_within_block: 1, replicate: 1, pressure: 1 },
      { run_order: 2, block: 1, arm: "reference", order_within_block: 2, replicate: 1, pressure: 2 }], factors: ["pressure"],
  },
  D05_effectiveness: { status: "INCONCLUSIVE", design: "difference_in_differences", estimate: null, causal_claim: false,
    assumptions: ["Parallel trends cannot be established."], qualification: "Sensitivity result crosses zero.", diagnostics: { pretrend: "NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND" },
    sensitivity: { bounds: [-0.2, 0.3] }, attrition: { excluded: 1 },
    pretrend_stability_placebo: { status: "NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND", ci95: [-1.1, -0.9] },
    population_compatibility: { status: "MATCHED_DECLARED_CATEGORICAL_COMPOSITION", fields: ["product_id"] },
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
    expect(within(d01).getByText("Uncertainty method and independent-unit mapping")).toBeTruthy();
    expect(within(d01).getByText(/declared_independent_unit_field/)).toBeTruthy();
    expect(within(d01).getByText(/NESTED/)).toBeTruthy();
    expect(within(d01).getByText(/sign_reversal_observed/)).toBeTruthy();
    expect(within(d01).getByText(/Independent time and group holdout performance/)).toBeTruthy();
    expect(within(d01).getAllByText(/COMPLETED_DIAGNOSTIC/).length).toBeGreaterThan(0);
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
    expect(within(d02).getByText("ADVISORY_POINTWISE_SCREENING_ONLY")).toBeTruthy();
    expect(within(d02).getByText(/Selection among cells can inflate false-feasible findings/)).toBeTruthy();
    expect(within(d02).getByText(/Independent candidate evaluation/)).toBeTruthy();
    expect(within(d02).getByText("Simultaneous exact-setting calibration")).toBeTruthy();
    expect(within(d02).getAllByText(/simultaneous exact-setting panel interval/).length).toBeGreaterThan(0);
    expect(within(d02).getAllByText(/Passes finite exact-setting panel screen under unverified assumptions/).length).toBeGreaterThan(0);
    expect(within(d02).getByText(/SYN-DO02-INTERLEAVED-001/)).toBeTruthy();
  });

  it("shows why held-out process rows were excluded from exact-setting evaluation", () => {
    render(<P4Panel sourcePreview={sourcePreview} evidence={evidence} />);
    const d02 = screen.getByRole("region", { name: "D02 · Evidence-supported process window" });
    const evaluation = within(d02).getByRole("table", {
      name: "Untouched evaluation by selected setting and matching fixed-control population; descriptive only",
    });
    expect(within(evaluation).getByText("NO_EXACT_SETTING_EVALUATION_DATA")).toBeTruthy();
    expect(within(evaluation).getByRole("cell", { name: "12" })).toBeTruthy();
    expect(within(evaluation).getByRole("cell", { name: "0" })).toBeTruthy();
    expect(within(d02).getByText("Complete-set selected-candidate failure audit")).toBeTruthy();
    expect(within(d02).getAllByText(/not a multiplicity-adjusted or population guarantee/).length).toBeGreaterThan(0);
  });

  it("surfaces the optional three-preperiod curvature placebo in D05 evidence", () => {
    render(<P4Panel sourcePreview={sourcePreview} evidence={evidence} />);
    const d05 = screen.getByRole("region", { name: "D05 · Change effectiveness" });
    expect(within(d05).getByText(/pretrend_stability_placebo/)).toBeTruthy();
    expect(within(d05).getAllByText(/NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND/).length).toBeGreaterThan(0);
    expect(within(d05).getByText(/MATCHED_DECLARED_CATEGORICAL_COMPOSITION/)).toBeTruthy();
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
    expect(screen.getByText(/marginal 95% interval \[87.9,88.5\]/)).toBeTruthy();
    expect(screen.getByText("Family-wise mean uncertainty envelope")).toBeTruthy();
    expect(screen.getByText(/Bonferroni family-wise mean interval \[87.7,88.7\]/)).toBeTruthy();
    expect(screen.getAllByText(/NO_FAMILYWISE_INTERVAL_SEPARATED_DOMINATOR/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/not multiplicity-adjusted/).length).toBeGreaterThan(0);
    expect(screen.getByText("No causal claim is made from these observed tradeoffs.")).toBeTruthy();
  });

  it("surfaces D03 constraint-based selection and excluded units", () => {
    const limitedEvidence = structuredClone(evidence);
    const artifact = limitedEvidence.artifacts?.[0] as Record<string, unknown>;
    const tradeoffs = artifact.D03_tradeoffs as Record<string, unknown>;
    tradeoffs.status = "LIMITED_SCOPE";
    tradeoffs.selection_warning = "Candidate means describe only the eligible subset; excluded units are reported.";
    tradeoffs.constraint_exclusion_audit = { status: "DESCRIPTIVE_CONSTRAINT_SELECTION", excluded_independent_units: 43,
      interpretation: "Constraint-based selection can change compared populations; no adjusted inference." };
    const renderChart = vi.fn(() => <div role="img" aria-label="Host rendered limited-scope Pareto scatter" />);
    render(<P4Panel sourcePreview={sourcePreview} evidence={limitedEvidence} renderChart={renderChart} />);
    const d03 = screen.getByRole("region", { name: "D03 · Cross-step and multiobjective tradeoffs" });
    expect(within(d03).getByText("Constraint eligibility and excluded population")).toBeTruthy();
    expect(within(d03).getByText(/excluded_independent_units/)).toBeTruthy();
    expect(within(d03).getByText("Candidate means describe only the eligible subset; excluded units are reported.")).toBeTruthy();
    expect(renderChart).toHaveBeenCalledWith(expect.objectContaining({
      schema_version: "suite-chart.v1", kind: "scatter",
      title: "Observed Pareto setting means (limited scope)",
    }));
    expect(screen.getByRole("img", { name: "Host rendered limited-scope Pareto scatter" })).toBeTruthy();
  });

  it("shows D04 as a non-executed proposal and withholds unsupported causal D05", () => {
    render(<P4Panel sourcePreview={sourcePreview} evidence={evidence} />);
    expect(screen.getByText(/Proposed runs: 2\. Executed: false/)).toBeTruthy();
    expect(screen.getByText(/No equipment command is issued/)).toBeTruthy();
    expect(screen.getAllByText(/MODEL_BASED_INTERVAL_SCREEN_ONLY/).length).toBeGreaterThan(0);
    const d04 = screen.getByRole("region", { name: "D04 · Next experiment proposal" });
    const runTable = within(d04).getByRole("table", { name: "Proposed run order for engineer review" });
    expect(within(runTable).getByRole("columnheader", { name: "Arm" })).toBeTruthy();
    expect(within(d04).getByText(/ONE_SIDED_CHI_SQUARE_UPPER_CONFIDENCE_BOUND/)).toBeTruthy();
    expect(within(d04).getByText(/P4 does not recompute or authenticate it/)).toBeTruthy();
    expect(within(runTable).getByRole("columnheader", { name: "pressure" })).toBeTruthy();
    expect(within(runTable).getByRole("cell", { name: "candidate" })).toBeTruthy();
    expect(within(runTable).getByRole("cell", { name: "reference" })).toBeTruthy();
    expect(within(d04).getByText(/Confirm the candidate versus an engineer-supplied reference/)).toBeTruthy();
      expect(screen.getByText(/Observational DiD remains descriptive; conditional interpretation is withheld/)).toBeTruthy();
    expect(screen.getByText("NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND")).toBeTruthy();
  });

  it("shows pending external bound qualification and never labels observational DiD causal", () => {
    const conditionalEvidence = structuredClone(evidence);
    const artifact = conditionalEvidence.artifacts?.[0] as Record<string, unknown>;
    artifact.D05_effectiveness = { status: "ESTIMATED", design: "difference_in_differences", estimate: 1.5,
      causal_claim: false, conditional_assumptions_passed: true, conditional_interpretation_eligible: false,
      conditional_interpretation_scope: "PENDING_BOUND_SOURCE_QUALIFICATION",
      bound_source_qualification: "NOT_ESTABLISHED_BY_AVAILABLE_ADAPTER",
      causal_claim_limitation: "P4 cannot authenticate the bound.",
      sensitivity: { ci95_under_bound: [1.25, 1.75], point_estimate_tipping_point_abs_trend: 1.5,
        ci95_tipping_point_abs_trend: 1.5, bound_authentication: "NOT_VERIFIABLE_BY_P4" } };
    render(<P4Panel sourcePreview={sourcePreview} evidence={conditionalEvidence} />);
    const d05 = screen.getByRole("region", { name: "D05 · Change effectiveness" });
    expect(within(d05).getByText(/conditional interpretation is pending independent qualification/)).toBeTruthy();
    expect(within(d05).getByText(/NOT_ESTABLISHED_BY_AVAILABLE_ADAPTER/)).toBeTruthy();
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
