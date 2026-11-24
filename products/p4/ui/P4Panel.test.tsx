import * as React from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { P4Panel, type P4Evidence, type SourcePreview, type SuiteChartModel } from "./P4Panel";
import mcpPanelBridge from "../../../tests/fixtures/mcp_p4_panel_bridge.json";

const sourcePreview: SourcePreview = {
  status: "SYNTHETIC_ONLY", permission: "No company access configured.", semantic_version: "SYNTHETIC-NOT-APPROVED",
  grain: "one observation per independent lot", metric: "yield_index", unit: "index", scope: "held-out synthetic fixture",
  time_window: "2026-01-01 to 2026-01-31", coverage: { independent_lots: 12 },
};

const d02Grid = [
  { factors: { pressure: 2.0, temperature: 40 }, region_class: "observed", conservative_feasible: true, simultaneous_supported_candidate: true, evaluation_transfer_status: "COUNTEREVIDENCE_PANEL_STRUCTURE_MISMATCH", predictions: { yield_index: { estimate: 88.2, predictive_interval95: [87.5, 88.9], simultaneous_group_interval95: [87.2, 89.2], simultaneous_group_calibration_status: "AVAILABLE_UNDER_UNVERIFIED_EXCHANGEABILITY_ASSUMPTIONS", model_predictive_interval95: [87.8, 88.6], calibration_status: "LOCAL_GROUP_HOLDOUT_EMPIRICAL", calibration_units: 20, status: "ESTIMATED" } } },
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
    simultaneous_exact_setting_screen: { status: "AVAILABLE", status_scope: "ASSUMPTION_CONDITIONAL_EXACT_SETTING_PANEL_ONLY", calibration_unit_count: 20, familywise_alpha: 0.05, scope: "one future independent unit across a finite exact-setting panel", independent_evaluation_panel_compatibility: { status: "OBSERVED_PANEL_STRUCTURE_MISMATCH", evaluation_unit_count: 10, mismatched_units: 10, expected_observations_per_setting: 1, interpretation: "held-out row counts differ from the declared calibration panel" }, calibration_transfer_assessment: { status: "COUNTEREVIDENCE_PANEL_STRUCTURE_MISMATCH", observed_counterevidence: ["OBSERVED_PANEL_STRUCTURE_MISMATCH"], evaluation_panel_status: "OBSERVED_PANEL_STRUCTURE_MISMATCH", unseen_evaluation_strata_count: null, unseen_evaluation_units: null, interpretation: "held-out evaluation panel differs; no future-population coverage validation" }, limitations: ["no interpolation coverage", "exchangeability unverified"] },
    uncertainty_rule: "All local group-held-out empirical intervals using a 95% order-statistic rank satisfy the explicit metric limits; this does not guarantee conditional coverage.",
    calibration: { method: "local_grouped_holdout_absolute_error", coverage_guarantee: "none; local selection does not establish conditional coverage", group_field: "lot_id", training_unit_count: 30, calibration_unit_count: 20, minimum_local_calibration_units: 19, split_reference: "SYN-DO02-INTERLEAVED-001" },
    independent_candidate_evaluation: { status: "DESCRIPTIVE", evaluated_candidate_count: 1, unevaluated_candidate_count: 0, method: "No population or simultaneous guarantee.",
      partition_composition_diagnostic: { status: "DESCRIPTIVE", fields: ["tool_id", "event_year"],
        partitions: { TRAIN: { independent_units: 30, assignable_units: 30, unassignable_units_missing_or_mixed_strata: 0,
          categories: [{ values: { tool_id: "TOOL-A", event_year: 2026 }, independent_units: 30, fraction_of_assignable_units: 1 }] },
          CALIBRATION: { independent_units: 20, assignable_units: 20, unassignable_units_missing_or_mixed_strata: 0,
            categories: [{ values: { tool_id: "TOOL-A", event_year: 2026 }, independent_units: 20, fraction_of_assignable_units: 1 }] } },
        comparisons: [{ from_partition: "TRAIN", to_partition: "CALIBRATION", categorical_total_variation_distance: 0 }],
        evaluation_partition_status: "NOT_PROVIDED", evaluation_strata_absent_from_calibration_count: null,
        evaluation_units_in_strata_absent_from_calibration: null,
        unseen_evaluation_strata: null, interpretation: "Descriptive only; not a test of exchangeability." },
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
    familywise_mean_envelope: { status: "AVAILABLE_APPROXIMATE_BONFERRONI_ENVELOPE", familywise_confidence_target: 0.95, mean_parameter_count: 2,
      method: "Bonferroni simultaneous independent-unit Student-t mean rectangles" },
    objective_metrics: [{ metric: "yield_index", direction: "maximize", unit: "index" }, { metric: "defect_rate", direction: "minimize", unit: "count" }],
    pareto_setting_ids: ["SYN-SETTING-01"], pareto_values: [{ id: "SYN-SETTING-01", yield_index: 88.2, defect_rate: 1.3 }],
    candidate_settings: [{ id: "SYN-SETTING-01", factors: { pressure: 2 }, independent_units: 12,
      means: { yield_index: 88.2, defect_rate: 1.3 },
      uncertainty: { yield_index: { marginal_ci95: [87.9, 88.5], familywise_ci95: [87.7, 88.7],
          unit_value_min: 87.5, unit_value_max: 89, familywise_ci95_method: "Bonferroni simultaneous independent-unit Student-t mean rectangles" },
        defect_rate: { marginal_ci95: [1.1, 1.5], familywise_ci95: [1.0, 1.6],
          unit_value_min: 1.0, unit_value_max: 1.7, familywise_ci95_method: "Bonferroni simultaneous independent-unit Student-t mean rectangles" } },
      mean_pareto_status: "NONDOMINATED_BY_MEANS", uncertainty_dominance_status: "NO_INTERVAL_SEPARATED_DOMINATOR",
      familywise_dominance_status: "NO_FAMILYWISE_INTERVAL_SEPARATED_DOMINATOR", familywise_dominated_by: [] }],
  },
  D04_experiment_proposal: { status: "PROPOSED", run_count: 2, design: "randomized blocked D02 candidate confirmation", executed: false,
    qualification: "Engineer review and authorization required.", authorization_fields: ["reviewer"], power: {
      qualification: "prospective only", paired_difference_sd_basis: "ONE_SIDED_CHI_SQUARE_UPPER_CONFIDENCE_BOUND",
      paired_difference_sd_confidence_level: 0.95, paired_difference_sd_degrees_of_freedom: 29,
      paired_sd_scope: "caller-supplied conservative upper bound; P4 does not recompute or authenticate it" },
    objective_statement: "Confirm the candidate versus an engineer-supplied reference.",
    objective: { source: "experiment_design.objective_statement",
      metrics: [{ metric: "yield_index", unit: "index", direction: "maximize", min: 85, max: null }],
      selection_policy: "no process setting is automatically selected", metric: "yield_index", unit: "index", direction: "maximize", minimum_detectable_effect: 1.0 },
    factor_definitions: [{ name: "pressure", unit: "kPa", approved_bounds: [1, 3], role: "controllable" }],
    information_value: { status: "APPROXIMATE", method: "blocked contrast", qualification: "planning diagnostic only" },
    pre_execution_uncertainty: { status: "NOT_ESTIMATED_FOR_NEW_RUNS", reason: "outcomes are not yet observed" },
    candidate_evidence: { region_class: "observed", simultaneous_supported_candidate: false, target_metric_interval95: [87.5, 88.9] },
    constraint_evaluation: { status: "MODEL_BASED_INTERVAL_SCREEN_ONLY", constraint_metrics: ["defect_rate"], qualification: "No feasibility guarantee." },
    runs: [{ run_order: 1, block: 1, arm: "candidate", order_within_block: 1, replicate: 1, pressure: 1 },
      { run_order: 2, block: 1, arm: "reference", order_within_block: 2, replicate: 1, pressure: 2 }], factors: ["pressure"],
  },
  D05_effectiveness: { status: "INCONCLUSIVE", design: "difference_in_differences", estimate: null, causal_claim: false,
    reason: "DiD period labels conflict with the documented intervention cutoff.",
    timing_diagnostic: { status: "PERIOD_CUTOFF_CONFLICT", period: "post" },
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
  it("renders evidence produced by the official MCP-to-P4 workflow through the shared panel contract", () => {
    const bridge = mcpPanelBridge as unknown as {
      source_preview: SourcePreview;
      analysis_evidence: P4Evidence;
    };
    const renderChart = vi.fn((model: SuiteChartModel) => <div data-testid={`shared-${model.chart_id}`} />);
    render(<P4Panel sourcePreview={bridge.source_preview} evidence={bridge.analysis_evidence} renderChart={renderChart} />);
    for (const section of ["D01 · Factor sensitivity", "D02 · Process-window evidence and hypotheses",
      "D03 · Cross-step and multiobjective tradeoffs", "D04 · Next experiment proposal", "D05 · Change effectiveness"]) {
      expect(screen.getByRole("region", { name: section })).toBeTruthy();
    }
    expect(screen.getByText("SYNTHETIC-SEMANTICS-1")).toBeTruthy();
    expect(screen.getByText("No company source permission is configured.", { exact: false })).toBeTruthy();
    expect(screen.getAllByText(/Interpolated settings are unvalidated model hypotheses and require exact-setting confirmation/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/does not validate a process window, conditional coverage, or future performance/).length).toBeGreaterThan(0);
    expect(screen.getByRole("table", { name: /Observed Pareto setting means/ })).toBeTruthy();
    expect(renderChart).toHaveBeenCalledWith(expect.objectContaining({ chart_id: "p4-supported-pareto", kind: "scatter" }));
    expect(screen.getByText(/SYN-AUDIT-READ-1/)).toBeTruthy();

    const d02 = screen.getByRole("region", { name: "D02 · Process-window evidence and hypotheses" });
    expect(within(d02).getByText(/advisory hypothesis, not validated feasibility/)).toBeTruthy();
    const cells = within(d02).getByRole("table", { name: /Advisory screening cells/ });
    expect(within(cells).getByRole("columnheader", { name: "Exact-setting independent evaluation" })).toBeTruthy();
    expect(within(cells).getAllByText(/MODEL_INTERPOLATION_ADVISORY_REQUIRES_EXACT_CONFIRMATION/).length).toBeGreaterThan(0);
    expect(within(cells).getAllByText(/PROPOSE_EXACT_SETTING_CONFIRMATION_ON_INDEPENDENT_LOTS/).length).toBeGreaterThan(0);
    expect(within(cells).getAllByText(/NO_EXACT_SETTING_EVALUATION_DATA; 0 independent lots/).length).toBeGreaterThan(0);

    const d04 = screen.getByRole("region", { name: "D04 · Next experiment proposal" });
    const design = within(d04).getByRole("table", { name: "Design and authorization requirements" });
    for (const field of ["objective_statement", "factor_definitions", "information_value",
      "pre_execution_uncertainty", "required_engineer_review", "evidence_required_before_next_iteration"]) {
      expect(within(design).getByRole("row", { name: new RegExp(field) })).toBeTruthy();
    }
    expect(within(design).getByText(/estimate lot-clustered response surfaces/)).toBeTruthy();
    expect(within(design).getByText(/SYNTHETIC-PRESSURE/)).toBeTruthy();
    expect(within(design).getByText(/NOT_ESTIMATED_FOR_NEW_RUNS/)).toBeTruthy();
    expect(within(d04).getByRole("table", { name: "Proposed run order for engineer review" })).toBeTruthy();
  });

  it("renders the MCP permission refusal without positive P4 findings or charts", () => {
    const bridge = mcpPanelBridge as unknown as {
      source_preview: SourcePreview;
      refusal_evidence: P4Evidence;
    };
    const renderChart = vi.fn(() => <div data-testid="unexpected-shared-chart" />);
    render(<P4Panel sourcePreview={bridge.source_preview} evidence={bridge.refusal_evidence} renderChart={renderChart} />);
    expect(screen.getByText(/Positive findings and charts are withheld because this result is refused/)).toBeTruthy();
    expect(screen.queryByRole("region", { name: /D0[1-5]/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /D0[1-5]/ })).toBeNull();
    expect(screen.queryByTestId("unexpected-shared-chart")).toBeNull();
    expect(renderChart).not.toHaveBeenCalled();
  });

  it("keeps large evidence arrays collapsed while preserving exact-value inspection", async () => {
    const user = userEvent.setup();
    const detailedEvidence = structuredClone(evidence);
    const dossier = detailedEvidence.artifacts?.[0] as Record<string, unknown>;
    const observedWindow = dossier.D02_observed_process_window as Record<string, unknown>;
    observedWindow.candidate_observation_ids = Array.from({ length: 300 }, (_, index) => `SYN-OBS-${index}`);

    render(<P4Panel sourcePreview={sourcePreview} evidence={detailedEvidence} />);
    const d02 = screen.getByRole("region", { name: "D02 · Process-window evidence and hypotheses" });
    const observed = within(d02).getByRole("table", { name: "Observed settings and scope" });
    const ids = within(observed).getByRole("row", { name: /candidate_observation_ids/ });
    const expand = within(ids).getByText("Show 300 items");
    expect(expand).toBeTruthy();
    expect(within(ids).queryByText("SYN-OBS-299")).toBeNull();

    await user.click(expand);
    expect(within(ids).getByText((content) => content.includes("SYN-OBS-299"))).toBeTruthy();
  });

  it("shows when independent evaluation withholds the entire D02 candidate set", () => {
    const withheldEvidence = structuredClone(evidence);
    const dossier = withheldEvidence.artifacts?.[0] as Record<string, unknown>;
    const supported = dossier.D02_supported_region as Record<string, unknown>;
    supported.status = "INCONCLUSIVE";
    supported.candidate_count = 0;
    supported.screened_candidate_count = 1;
    supported.candidate_screening_status = "WITHHELD_BY_INDEPENDENT_COUNTEREVIDENCE";
    supported.candidate_counterevidence = {
      status: "WITHHELD_BY_CALIBRATION_TRANSFER_COUNTEREVIDENCE",
      transfer_status: "COUNTEREVIDENCE_UNSEEN_EVALUATION_STRATA",
      observed_transfer_counterevidence: ["UNSEEN_EVALUATION_STRATA"],
    };
    supported.simultaneous_exact_setting_screen = { calibration_transfer_assessment: {
      status: "COUNTEREVIDENCE_UNSEEN_EVALUATION_STRATA",
      observed_counterevidence: ["UNSEEN_EVALUATION_STRATA"],
      unseen_evaluation_units: 10,
    } };
    supported.grid = [{ factors: { pressure: 0.5, power: 0.5 }, region_class: "interpolated",
      conservative_feasible: true, screened_candidate: true, supported_candidate: false,
      candidate_screening_status: "WITHHELD_BY_INDEPENDENT_COUNTEREVIDENCE",
      simultaneous_supported_candidate: false, support: { nearby_independent_units: 30, nearby_distinct_settings: 3 },
      predictions: { quality: { estimate: 0.1, predictive_interval95: [0.08, 0.12],
        calibration_status: "LOCAL_GROUP_HOLDOUT_EMPIRICAL", calibration_units: 20 } } }];
    supported.independent_candidate_evaluation = { candidate_selection_audit: {
      status: "DESCRIPTIVE_SETWISE_DIAGNOSTIC", complete_independent_units: 20,
      observed_any_infeasible_units: 20, observed_any_infeasible_fraction: 1,
    }, candidates: [] };

    render(<P4Panel sourcePreview={sourcePreview} evidence={withheldEvidence} />);

    const d02 = screen.getByRole("region", { name: "D02 · Process-window evidence and hypotheses" });
    expect(within(d02).getByText(/No process-window candidates are available for advisory review/)).toBeTruthy();
    expect(within(d02).getAllByText(/COUNTEREVIDENCE_UNSEEN_EVALUATION_STRATA/).length).toBeGreaterThan(0);
    expect(within(d02).getByRole("columnheader", { name: "Recommendation status" })).toBeTruthy();
    expect(within(d02).getByText("Withheld by independent counterevidence")).toBeTruthy();
  });

  it("shows per-cell independent evaluation and exact confirmation action for interpolation", () => {
    const interpolationEvidence = structuredClone(evidence);
    const dossier = interpolationEvidence.artifacts?.[0] as Record<string, unknown>;
    const supported = dossier.D02_supported_region as Record<string, unknown>;
    supported.grid = [{ ...d02Grid[1], screened_candidate: true, supported_candidate: true,
      candidate_review_status: "MODEL_INTERPOLATION_ADVISORY_REQUIRES_EXACT_CONFIRMATION",
      required_engineer_action: "PROPOSE_EXACT_SETTING_CONFIRMATION_ON_INDEPENDENT_LOTS",
      independent_evaluation: { status: "NO_EXACT_SETTING_EVALUATION_DATA", independent_units: 0,
        observed_infeasible_units: null } }];

    render(<P4Panel sourcePreview={sourcePreview} evidence={interpolationEvidence} />);
    const d02 = screen.getByRole("region", { name: "D02 · Process-window evidence and hypotheses" });
    const cells = within(d02).getByRole("table", { name: /Advisory screening cells/ });
    expect(within(cells).getByRole("columnheader", { name: "Exact-setting independent evaluation" })).toBeTruthy();
    expect(within(cells).getByRole("columnheader", { name: "Required engineer review" })).toBeTruthy();
    expect(within(cells).getByText(/NO_EXACT_SETTING_EVALUATION_DATA; 0 independent lots/)).toBeTruthy();
    expect(within(cells).getByText(/PROPOSE_EXACT_SETTING_CONFIRMATION_ON_INDEPENDENT_LOTS/)).toBeTruthy();
    expect(within(d02).getByText(/Interpolated cells are model-based hypotheses/)).toBeTruthy();
    expect(within(d02).getByText(/Pointwise local intervals are empirical diagnostics/)).toBeTruthy();
    expect(within(d02).getByRole("columnheader", { name: "Pointwise screening result" })).toBeTruthy();
  });

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

  it("explains when zero observed variance makes a D03 interval unestimable", () => {
    const zeroVarianceEvidence = structuredClone(evidence);
    const artifact = zeroVarianceEvidence.artifacts?.[0] as Record<string, unknown>;
    const d03 = artifact.D03_tradeoffs as Record<string, unknown>;
    d03.status = "LIMITED_SCOPE";
    d03.uncertainty_available = false;
    d03.uncertainty_limitations = [
      "zero observed variance leaves the marginal Student-t interval unestimable; it does not establish zero population uncertainty",
    ];
    const candidate = (d03.candidate_settings as Array<Record<string, unknown>>)[0];
    const uncertainty = candidate.uncertainty as Record<string, Record<string, unknown>>;
    uncertainty.yield_index.marginal_ci95 = null;
    uncertainty.yield_index.marginal_ci95_status = "NOT_ESTIMABLE_ZERO_OBSERVED_VARIANCE";
    render(<P4Panel sourcePreview={sourcePreview} evidence={zeroVarianceEvidence} />);
    const d03Region = screen.getByRole("region", { name: "D03 · Cross-step and multiobjective tradeoffs" });
    expect(within(d03Region).getByText(/zero observed variance does not establish zero population uncertainty/)).toBeTruthy();
  });

  it("surfaces near-collinearity as a heuristic coefficient-instability warning", () => {
    const unstableEvidence = structuredClone(evidence);
    const artifact = unstableEvidence.artifacts?.[0] as Record<string, unknown>;
    const d01 = artifact.D01_sensitivity as Record<string, unknown>;
    d01.diagnostics = {
      rank: 3, condition_proxy: 102612.6,
      condition_proxy_interpretation: {
        status: "SEVERE_HEURISTIC", elevated_threshold: 100, severe_threshold: 1000,
        method: "squared pivoted-QR diagonal ratio; descriptive screening thresholds only",
        guarantee: "none; does not replace rank/identifiability analysis or validate the selected formula",
      },
    };
    d01.diagnostic_warnings = [
      "severe near-collinearity heuristic: separate coefficient estimates may be unstable; inspect confidence intervals and formula sensitivity; this QR diagonal-ratio threshold is not a universal identifiability test",
    ];
    render(<P4Panel sourcePreview={sourcePreview} evidence={unstableEvidence} />);
    const d01Region = screen.getByRole("region", { name: "D01 · Factor sensitivity" });
    expect(within(d01Region).getByText(/"status":"SEVERE_HEURISTIC"/)).toBeTruthy();
    expect(within(d01Region).getAllByText(/condition_proxy/).length).toBeGreaterThan(0);
    expect(within(d01Region).getByText(/separate coefficient estimates may be unstable/)).toBeTruthy();
  });

  it("explains when cluster-size concentration withholds uncertainty", () => {
    const imbalancedEvidence = structuredClone(evidence);
    const artifact = imbalancedEvidence.artifacts?.[0] as Record<string, unknown>;
    const d01 = artifact.D01_sensitivity as Record<string, unknown>;
    d01.status = "INCONCLUSIVE";
    d01.terms = { pressure: { estimate: 0.4, ci95: null, standard_error: null } };
    d01.inference = {
      covariance: "cluster", independent_cluster_count: 30, row_share_effective_cluster_count: 3.75,
      cluster_size_diagnostic: { method: "inverse_Herfindahl_of_observation_count_shares",
        row_share_effective_cluster_count: 3.75, dominant_cluster_row_share: 0.508,
        minimum_required_effective_clusters: 30, status: "INSUFFICIENT_EFFECTIVE_CLUSTER_COUNT" },
    };
    d01.diagnostic_warnings = ["cluster-robust intervals withheld: observation-count concentration yields 3.75 effective clusters, below minimum_clusters=30"];
    render(<P4Panel sourcePreview={sourcePreview} evidence={imbalancedEvidence} />);
    const d01Region = screen.getByRole("region", { name: "D01 · Factor sensitivity" });
    expect(within(d01Region).getAllByText(/row_share_effective_cluster_count/).length).toBeGreaterThan(0);
    expect(within(d01Region).getByText(/observation-count concentration yields 3.75 effective clusters/)).toBeTruthy();
    expect(within(d01Region).getByText(/95% interval Not provided/)).toBeTruthy();
  });

  it("shows sparse binary cluster-level exposure support and its abstention", () => {
    const sparseExposureEvidence = structuredClone(evidence);
    const artifact = sparseExposureEvidence.artifacts?.[0] as Record<string, unknown>;
    const d01 = artifact.D01_sensitivity as Record<string, unknown>;
    d01.status = "INCONCLUSIVE";
    d01.reason = "binary cluster-level factor has fewer than 10 independent clusters in one level; model uncertainty is withheld";
    d01.terms = { exposed: { estimate: 0.2, ci95: null, standard_error: null } };
    d01.inference = {
      covariance: "cluster", independent_cluster_count: 30,
      cluster_level_factor_support: [{ factor: "exposed", design: "BINARY_FACTOR_CONSTANT_WITHIN_CLUSTER",
        cluster_count_by_level: [3, 27], minimum_clusters_per_level: 10,
        status: "INSUFFICIENT_CLUSTER_LEVEL_SUPPORT",
        interpretation: "descriptive abstention screen; passing does not guarantee coverage" }],
    };
    d01.diagnostic_warnings = ["cluster-robust intervals withheld: binary cluster-level factor(s) exposed have fewer than 10 independent clusters in one level"];
    render(<P4Panel sourcePreview={sourcePreview} evidence={sparseExposureEvidence} />);
    const d01Region = screen.getByRole("region", { name: "D01 · Factor sensitivity" });
    expect(within(d01Region).getAllByText(/INSUFFICIENT_CLUSTER_LEVEL_SUPPORT/).length).toBeGreaterThan(0);
    expect(within(d01Region).getAllByText(/\"cluster_count_by_level\":\[3,27\]/).length).toBeGreaterThan(0);
    expect(within(d01Region).getByText(/fewer than 10 independent clusters in one level/)).toBeTruthy();
    expect(within(d01Region).getByText(/95% interval Not provided/)).toBeTruthy();
  });

  it("shows crossed chamber and product dependence as an uncertainty refusal", () => {
    const crossedEvidence = structuredClone(evidence);
    const artifact = crossedEvidence.artifacts?.[0] as Record<string, unknown>;
    const d01 = artifact.D01_sensitivity as Record<string, unknown>;
    d01.status = "INCONCLUSIVE";
    d01.interpretation = "Point estimate retained; intervals withheld for declared crossed group dependence.";
    d01.terms = { pressure: { estimate: 0.4, ci95: null, standard_error: null } };
    d01.inference = {
      covariance: "cluster", declared_independent_unit_field: "lot_id",
      shared_dependence: { status: "CROSSED_DEPENDENCE_DETECTED", fields: [
        { field: "chamber", crossed_group_count: 8 },
        { field: "product", crossed_group_count: 6 },
      ] },
    };
    d01.diagnostic_warnings = [
      "robust intervals withheld: declared shared-dependence groups span independent units; configured covariance does not account for crossed dependence",
    ];
    render(<P4Panel sourcePreview={sourcePreview} evidence={crossedEvidence} />);
    const d01Region = screen.getByRole("region", { name: "D01 · Factor sensitivity" });
    expect(within(d01Region).getAllByText(/CROSSED_DEPENDENCE_DETECTED/).length).toBeGreaterThan(0);
    expect(within(d01Region).getAllByText(/\"field\":\"chamber\"/).length).toBeGreaterThan(0);
    expect(within(d01Region).getByText(/intervals withheld.*crossed dependence/)).toBeTruthy();
    expect(within(d01Region).getByText(/95% interval Not provided/)).toBeTruthy();
  });

  it("filters the D02 table while preserving observed, interpolated, and unsupported labels", () => {
    render(<P4Panel sourcePreview={sourcePreview} evidence={evidence} />);
    const d02 = screen.getByRole("region", { name: "D02 · Process-window evidence and hypotheses" });
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
    expect(within(d02).getAllByText(/OBSERVED_PANEL_STRUCTURE_MISMATCH/).length).toBeGreaterThan(0);
    expect(within(d02).getByText(/expected_observations_per_setting/)).toBeTruthy();
    const population = within(d02).getByRole("table", {
      name: "Independent-unit population strata by partition; descriptive, not an exchangeability test",
    });
    expect(within(population).getByRole("rowheader", { name: "CALIBRATION" })).toBeTruthy();
    expect(within(population).getAllByText(/TOOL-A/).length).toBeGreaterThan(0);
    const composition = within(d02).getByRole("table", { name: "Between-partition composition distances and evaluation strata absent from calibration" });
    expect(within(composition).getByText("evaluation_partition_status")).toBeTruthy();
    expect(within(composition).getByText("NOT_PROVIDED")).toBeTruthy();
    expect(within(composition).getByText("evaluation_strata_absent_from_calibration_count")).toBeTruthy();
    expect(within(composition).getAllByText("Not provided").length).toBeGreaterThan(0);
    expect(within(d02).getAllByText(/simultaneous exact-setting panel interval/).length).toBeGreaterThan(0);
    expect(within(d02).getByText("Calibration transfer assessment; descriptive, not validation")).toBeTruthy();
    expect(within(d02).getAllByText(/COUNTEREVIDENCE_PANEL_STRUCTURE_MISMATCH/).length).toBeGreaterThan(0);
    expect(within(d02).getAllByText(/Passes calibration-panel screen under unverified assumptions; transfer: COUNTEREVIDENCE_PANEL_STRUCTURE_MISMATCH/).length).toBeGreaterThan(0);
    expect(within(d02).getByText(/SYN-DO02-INTERLEAVED-001/)).toBeTruthy();
  });

  it("shows exact-panel outcome misses as descriptive calibration-transfer counterevidence", () => {
    const shiftedEvidence = structuredClone(evidence);
    const artifact = shiftedEvidence.artifacts?.[0] as Record<string, unknown>;
    const supported = artifact.D02_supported_region as Record<string, unknown>;
    const simultaneous = supported.simultaneous_exact_setting_screen as Record<string, unknown>;
    simultaneous.calibration_transfer_assessment = {
      status: "COUNTEREVIDENCE_CALIBRATION_BAND_MISSES",
      evaluation_panel_status: "DESCRIPTIVE_PANEL_STRUCTURE_MATCH",
      calibration_to_evaluation_total_variation: 0,
      observed_counterevidence: ["OBSERVED_CALIBRATION_BAND_MISSES"],
      heldout_band_evaluation: {
        status: "DESCRIPTIVE_HELDOUT_BAND_EVALUATION", evaluation_units: 10,
        complete_panel_units: 10, mismatched_panel_units: 0,
        missed_any_interval_units: 8, missed_any_interval_fraction: 0.8,
        transfer_signal: "OBSERVED_CALIBRATION_BAND_MISSES",
        interpretation: "Observed held-out interval misses are transfer counterevidence; zero observed misses do not validate coverage.",
        candidate_selection_influence: false, coverage_guarantee: "none; descriptive held-out counterevidence only",
      },
      interpretation: "Observed evaluation outcomes provide counterevidence; no future-population coverage is estimated.",
    };
    render(<P4Panel sourcePreview={sourcePreview} evidence={shiftedEvidence} />);
    const d02 = screen.getByRole("region", { name: "D02 · Process-window evidence and hypotheses" });
    expect(within(d02).getAllByText(/COUNTEREVIDENCE_CALIBRATION_BAND_MISSES/).length).toBeGreaterThan(0);
    expect(within(d02).getAllByText(/complete_panel_units/).length).toBeGreaterThan(0);
    expect(within(d02).getAllByText(/missed_any_interval_fraction/).length).toBeGreaterThan(0);
    expect(within(d02).getAllByText(/zero observed misses do not validate coverage/).length).toBeGreaterThan(0);
    expect(within(d02).getAllByText(/candidate_selection_influence/).length).toBeGreaterThan(0);
  });

  it("shows why held-out process rows were excluded from exact-setting evaluation", () => {
    render(<P4Panel sourcePreview={sourcePreview} evidence={evidence} />);
    const d02 = screen.getByRole("region", { name: "D02 · Process-window evidence and hypotheses" });
    const evaluation = within(d02).getByRole("table", {
      name: "Untouched evaluation by selected setting and matching fixed-control population; descriptive only",
    });
    expect(within(evaluation).getByText("NO_EXACT_SETTING_EVALUATION_DATA")).toBeTruthy();
    expect(within(evaluation).getByRole("cell", { name: "12" })).toBeTruthy();
    expect(within(evaluation).getByRole("cell", { name: "0" })).toBeTruthy();
    expect(within(d02).getByText("Complete-set selected-candidate failure audit")).toBeTruthy();
    expect(within(d02).getAllByText(/not a multiplicity-adjusted or population guarantee/).length).toBeGreaterThan(0);
  });

  it("shows when mixed evaluation strata make calibration transfer diagnostics incomplete", () => {
    const challenged = JSON.parse(JSON.stringify(evidence)) as P4Evidence;
    const dossier = challenged.artifacts?.[0] as Record<string, unknown>;
    const supported = dossier.D02_supported_region as Record<string, unknown>;
    const simultaneous = supported.simultaneous_exact_setting_screen as Record<string, unknown>;
    simultaneous.calibration_transfer_assessment = {
      status: "INSUFFICIENT_TRANSFER_DIAGNOSTICS",
      observed_counterevidence: ["INSUFFICIENT_ASSIGNABLE_STRATA"],
      unassignable_strata_units: { CALIBRATION: 0, EVALUATION: 1 },
      interpretation: "Available evaluation strata are incomplete; transfer is not established.",
    };

    render(<P4Panel sourcePreview={sourcePreview} evidence={challenged} />);
    const d02 = screen.getByRole("region", { name: "D02 · Process-window evidence and hypotheses" });
    const transfer = within(d02).getByRole("table", {
      name: "Calibration transfer assessment; descriptive, not validation",
    });
    expect(within(transfer).getByRole("rowheader", { name: "status" })).toBeTruthy();
    expect(within(transfer).getByText("INSUFFICIENT_TRANSFER_DIAGNOSTICS")).toBeTruthy();
    expect(within(transfer).getByText(/EVALUATION.*1/)).toBeTruthy();
    expect(within(transfer).getByText(/incomplete/)).toBeTruthy();
  });

  it("surfaces the optional three-preperiod curvature placebo in D05 evidence", () => {
    render(<P4Panel sourcePreview={sourcePreview} evidence={evidence} />);
    const d05 = screen.getByRole("region", { name: "D05 · Change effectiveness" });
    expect(within(d05).getByText(/pretrend_stability_placebo/)).toBeTruthy();
    expect(within(d05).getAllByText(/NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND/).length).toBeGreaterThan(0);
    expect(within(d05).getByText(/MATCHED_DECLARED_CATEGORICAL_COMPOSITION/)).toBeTruthy();
  });

  it("labels cluster-dependent D05 contrast as descriptive and exposes why uncertainty was withheld", () => {
    const challenged = structuredClone(evidence);
    const dossier = challenged.artifacts?.[0] as Record<string, unknown>;
    dossier.D05_effectiveness = {
      status: "INCONCLUSIVE", design: "difference_in_differences", estimate: null,
      descriptive_did_estimate: 0.42, uncertainty_status: "WITHHELD_SHARED_GROUP_DEPENDENCE",
      estimate_scope: "unadjusted difference in unit-level changes only",
      dependence_diagnostic: { status: "SHARED_GROUPS_DETECTED", fields: ["chamber_id"],
        shared_groups_by_field: { chamber_id: { shared_group_count: 5, max_independent_units_per_group: 6 } } },
      reason: "Declared chamber groups span units; cluster-aware inference is required.", causal_claim: false,
    };
    render(<P4Panel sourcePreview={sourcePreview} evidence={challenged} />);
    const d05 = screen.getByRole("region", { name: "D05 · Change effectiveness" });
    expect(within(d05).getByText(/Descriptive contrast: 0.42/)).toBeTruthy();
    expect(within(d05).getByText(/cluster-aware inference is required/)).toBeTruthy();
    const table = within(d05).getByRole("table", { name: "Uncertainty and sensitivity" });
    const dependence = within(table).getByRole("row", { name: /dependence_diagnostic/ });
    expect(within(dependence).getByText(/SHARED_GROUPS_DETECTED/)).toBeTruthy();
    expect(within(table).getByRole("row", { name: /ci95_welch_t_approximation/ }).textContent).toContain("Not provided");
  });

  it("shows the randomization-cluster estimand and effective inference counts", () => {
    const challenged = structuredClone(evidence);
    const dossier = challenged.artifacts?.[0] as Record<string, unknown>;
    dossier.D05_effectiveness = {
      status: "ESTIMATED", design: "randomized", estimate: 0.2, se: 0.3, welch_df: 8,
      ci95_welch_t_approximation: [-0.49, 0.89], causal_claim: true,
      inference_unit: "declared_randomization_cluster",
      inference_method: "Welch t interval over equally weighted declared randomization-cluster means",
      inference_unit_counts: { treatment: 5, control: 5 },
      cluster_size_summary: { estimand: "equal-weight cluster means; lot-weighted effect is not estimated",
        treatment: { randomization_clusters: 5, assigned_units: 21, assigned_units_per_cluster_min: 4,
          assigned_units_per_cluster_median: 4, assigned_units_per_cluster_max: 5 },
        control: { randomization_clusters: 5, assigned_units: 20, assigned_units_per_cluster_min: 4,
          assigned_units_per_cluster_median: 4, assigned_units_per_cluster_max: 4 } },
      assumptions: ["equal weight per randomization cluster defines the estimand"],
    };
    render(<P4Panel sourcePreview={sourcePreview} evidence={challenged} />);
    const d05 = screen.getByRole("region", { name: "D05 · Change effectiveness" });
    expect(within(d05).getByText(/equal weight per declared assignment cluster/)).toBeTruthy();
    const table = within(d05).getByRole("table", { name: "Uncertainty and sensitivity" });
    expect(within(table).getByRole("row", { name: /inference_unit_counts/ }).textContent).toContain('"treatment":5');
    expect(within(table).getByRole("row", { name: /inference_method/ }).textContent).toContain("cluster means");
    expect(within(d05).getByText(/not per lot when cluster sizes differ/)).toBeTruthy();
    expect(within(table).getByRole("row", { name: /cluster_size_summary/ }).textContent).toContain('"assigned_units":21');
  });

  it("shows arm-specific cointervention frequencies and withholds the DiD gate on imbalance", () => {
    const challenged = JSON.parse(JSON.stringify(evidence)) as P4Evidence;
    const dossier = challenged.artifacts?.[0] as Record<string, unknown>;
    const d05 = dossier.D05_effectiveness as Record<string, unknown>;
    d05.concurrent_intervention_diagnostic = {
      status: "DIFFERENTIAL_OR_INCOMPLETE_DECLARED_MIX",
      periods_with_different_group_proportions: ["post"],
      transitions_with_different_group_proportions: ["pre -> post"],
      period_category_counts: { treatment: { post: { none: 15, "SYN-COMED": 15 } }, control: { post: { none: 29, "SYN-COMED": 1 } } },
      interpretation: "Different declared cointervention proportions withhold the numerical assumption gate.",
    };
    d05.conditional_assumptions_passed = false;

    render(<P4Panel sourcePreview={sourcePreview} evidence={challenged} />);
    const d05Region = screen.getByRole("region", { name: "D05 · Change effectiveness" });
    const diagnosticRow = within(d05Region).getByRole("row", { name: /concurrent_intervention_diagnostic/ });
    expect(within(diagnosticRow).getByRole("rowheader", { name: "concurrent_intervention_diagnostic" })).toBeTruthy();
    expect(within(d05Region).getByText(/Concurrent intervention history: DIFFERENTIAL_OR_INCOMPLETE_DECLARED_MIX/)).toBeTruthy();
    fireEvent.click(within(diagnosticRow).getByText("Show 5 fields"));
    expect(within(diagnosticRow).getByText(/period_category_counts/)).toBeTruthy();
    expect(within(diagnosticRow).getByText(/SYN-COMED/)).toBeTruthy();
  });

  it("keeps native filter controls keyboard-focusable and in tab order", async () => {
    const user = userEvent.setup();
    render(<P4Panel sourcePreview={sourcePreview} evidence={evidence} />);
    const region = screen.getByLabelText("Evidence region") as HTMLSelectElement;
    region.focus();
    expect(document.activeElement).toBe(region);
    const feasibility = screen.getByLabelText("Pointwise model screen");
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
    expect(screen.getByText(/family-wise mean interval \[87.7,88.7\]/)).toBeTruthy();
    expect(screen.getByText(/independent-unit range 87.5 to 89/)).toBeTruthy();
    expect(screen.getByText(/Objectives: yield_index \(maximize, index\); defect_rate \(minimize, count\)/)).toBeTruthy();
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
    tradeoffs.unassessed_settings = [{ id: "SYN-SETTING-4", factors: { pressure: 4 },
      eligible_independent_units: 20, required_independent_units: 30,
      reason: "below independent-unit minimum" }];
    tradeoffs.constraint_exclusion_audit = { status: "DESCRIPTIVE_CONSTRAINT_SELECTION", excluded_independent_units: 43,
      interpretation: "Constraint-based selection can change compared populations; no adjusted inference." };
    const renderChart = vi.fn(() => <div role="img" aria-label="Host rendered limited-scope Pareto scatter" />);
    render(<P4Panel sourcePreview={sourcePreview} evidence={limitedEvidence} renderChart={renderChart} />);
    const d03 = screen.getByRole("region", { name: "D03 · Cross-step and multiobjective tradeoffs" });
    expect(within(d03).getByText("Constraint eligibility and excluded population")).toBeTruthy();
    expect(within(d03).getByText(/excluded_independent_units/)).toBeTruthy();
    expect(within(d03).getByText("Candidate means describe only the eligible subset; excluded units are reported.")).toBeTruthy();
    const unassessed = within(d03).getByRole("table", {
      name: "Observed settings not ranked because they missed the independent-unit minimum",
    });
    expect(within(unassessed).getByRole("rowheader", { name: "SYN-SETTING-4" })).toBeTruthy();
    expect(within(unassessed).getByText('{"pressure":4}')).toBeTruthy();
    expect(within(unassessed).getByText("20")).toBeTruthy();
    expect(within(unassessed).getByText("30")).toBeTruthy();
    expect(within(unassessed).getByText("below independent-unit minimum")).toBeTruthy();
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
    expect(within(d04).getByText(/approved_bounds/)).toBeTruthy();
    expect(within(d04).getByText(/NOT_ESTIMATED_FOR_NEW_RUNS/)).toBeTruthy();
      expect(screen.getByText(/Observational DiD remains descriptive; conditional interpretation is withheld/)).toBeTruthy();
    const d05 = screen.getByRole("region", { name: "D05 · Change effectiveness" });
    expect(within(d05).getByText(/period labels conflict with the documented intervention cutoff/)).toBeTruthy();
    expect(within(d05).getByText(/PERIOD_CUTOFF_CONFLICT/)).toBeTruthy();
    expect(screen.getByText("NOT_WITHIN_PRESPECIFIED_EQUIVALENCE_BOUND")).toBeTruthy();
  });

  it("shows the time-ordered independent-unit holdout and its caller-supplied scope", () => {
    const timed = structuredClone(evidence);
    const dossier = timed.artifacts?.[0] as Record<string, unknown>;
    const proposal = dossier.D04_experiment_proposal as Record<string, unknown>;
    proposal.grouped_surface_validation = {
      method: "grouped model-selection CV plus untouched chronological independent-unit holdout",
      validation_split: { type: "PREDECLARED_TIME_ORDERED_INDEPENDENT_UNIT_HOLDOUT",
        split_reference_status: "CALLER_SUPPLIED_NOT_AUTHENTICATED", timestamp_field: "event_ts",
        training_end: "2026-01-30T00:00:00+00:00", evaluation_start: "2026-01-31T00:00:00+00:00" },
      development_group_count: 30, evaluation_group_count: 6, selected_model: "quadratic",
      independent_evaluation: { rmse: 0.08 }, engineer_specified_maximum_rmse: 0.2,
    };
    render(<P4Panel sourcePreview={sourcePreview} evidence={timed} />);
    const d04 = screen.getByRole("region", { name: "D04 · Next experiment proposal" });
    const validation = within(d04).getByRole("table", { name: "Sequential model and holdout validation" });
    expect(within(validation).getByText("PREDECLARED_TIME_ORDERED_INDEPENDENT_UNIT_HOLDOUT")).toBeTruthy();
    expect(within(validation).getByText("CALLER_SUPPLIED_NOT_AUTHENTICATED")).toBeTruthy();
    expect(within(validation).getByText("0.08")).toBeTruthy();
    expect(within(validation).getByText("2026-01-31T00:00:00+00:00")).toBeTruthy();
  });

  it("renders objective-specific next-best options as alternatives rather than a batch", () => {
    const slate = structuredClone(evidence);
    const dossier = slate.artifacts?.[0] as Record<string, unknown>;
    dossier.D04_experiment_proposal = {
      status: "PROPOSED", design: "objective-specific sequential experiment alternatives",
      strategy: "next_best_multiobjective", run_count: 0, runs: [], executed: false,
      factors: ["pressure"], selection_policy: "one separately screened setting per declared objective; no combined score",
      objective_statement: "Offer separate outcome-specific alternatives.",
      qualification: "Values have objective-specific units and are not jointly probabilistic.",
      run_options: [
        { option_id: "OBJECTIVE-1", objective_metric: "yield", objective_direction: "maximize", objective_unit: "index",
          settings: { pressure: 1.5 }, expected_improvement: 0.3,
          prediction: { estimate: 88.1, mean_standard_error: 0.2, predictive_interval95: [87.7, 88.5] },
          constraint_predictions: { safety: { status: "MODEL_INTERVAL_WITHIN_SUPPLIED_BOUNDS", predictive_interval95: [0.1, 0.2] } },
          support: { nearest_normalized_distance: 0.1, nearby_observation_count: 80 },
          grouped_surface_validation: { evaluation_group_count: 20, independent_evaluation: { rmse: 0.4 } } },
        { option_id: "OBJECTIVE-2", objective_metric: "defect", objective_direction: "minimize", objective_unit: "rate",
          settings: { pressure: 2.5 }, expected_improvement: 0.02,
          prediction: { estimate: 1.8, mean_standard_error: 0.03, predictive_interval95: [1.74, 1.86] },
          support: { nearest_normalized_distance: 0.12, nearby_observation_count: 75 },
          grouped_surface_validation: { evaluation_group_count: 20, independent_evaluation: { rmse: 0.08 } } },
      ],
    };
    render(<P4Panel sourcePreview={sourcePreview} evidence={slate} />);
    const d04 = screen.getByRole("region", { name: "D04 · Next experiment proposal" });
    expect(within(d04).getByText(/Objective-specific alternatives: 2; each is one proposed run/)).toBeTruthy();
    const table = within(d04).getByRole("table", { name: /Objective-specific single-run alternatives/ });
    expect(within(table).getByRole("columnheader", { name: "Expected improvement in objective units" })).toBeTruthy();
    expect(within(table).getByRole("row", { name: /yield.*maximize; index.*1.5.*0.3/ })).toBeTruthy();
    expect(within(table).getByRole("row", { name: /defect.*minimize; rate.*2.5.*0.02/ })).toBeTruthy();
    expect(within(table).getByText(/safety.*MODEL_INTERVAL_WITHIN_SUPPLIED_BOUNDS/)).toBeTruthy();
    expect(within(d04).queryByRole("table", { name: "Proposed run order for engineer review" })).toBeNull();
    expect(within(d04).getByText(/no combined score/)).toBeTruthy();
  });

  it("shows pending external bound qualification and never labels observational DiD causal", () => {
    const conditionalEvidence = structuredClone(evidence);
    const artifact = conditionalEvidence.artifacts?.[0] as Record<string, unknown>;
    artifact.D05_effectiveness = { status: "ESTIMATED", design: "difference_in_differences", estimate: 1.5,
      intervention_timing_diagnostic: { status: "ALIGNED_TO_DECLARED_CUTOFF", timestamped_observations: 90 },
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
    expect(within(d05).getByText(/ALIGNED_TO_DECLARED_CUTOFF/)).toBeTruthy();
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
