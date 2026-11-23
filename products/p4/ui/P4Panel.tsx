import * as React from "react";
import { Fragment, type ReactNode, useMemo, useState } from "react";

export type P4Status = "VALID" | "PARTIAL" | "INCONCLUSIVE" | "REFUSED" | "ERROR";
export type ChartValue = string | number;

export interface SourcePreview {
  status: string;
  permission: string;
  semantic_version: string;
  grain: string;
  metric: string;
  unit: string;
  scope: string;
  time_window: string;
  coverage?: Record<string, number>;
}

export interface P4Claim {
  statement: string;
  category?: string;
  certainty?: string;
  method?: string;
  source_ids?: string[];
}

export interface P4Evidence {
  status: P4Status;
  investigation_id: string;
  claims: P4Claim[];
  limitations: string[];
  assumptions?: unknown[];
  sources?: Array<{ id: string; source_hash?: string; grain?: string }>;
  provenance?: { input_sha256?: string; engine_version?: string; method_version?: string; [key: string]: unknown };
  artifacts?: unknown[];
}

export interface SuiteChartModel {
  schema_version: "suite-chart.v1";
  chart_id: string;
  kind: "line" | "scatter";
  title: string;
  x_label: string;
  y_label: string;
  series: Array<{ id: string; label: string; style: "solid" | "dashed" | "markers" }>;
  points: Array<{ x: ChartValue; values: Record<string, number | null> }>;
}

export interface P4PanelProps {
  sourcePreview: SourcePreview;
  evidence?: P4Evidence | null;
  charts?: SuiteChartModel[];
  /** Provided by the shared suite host; P4 never owns a chart runtime. */
  renderChart?: (model: SuiteChartModel) => ReactNode;
}

type JsonObject = Record<string, unknown>;
type Dossier = JsonObject & {
  D01_sensitivity?: JsonObject;
  D02_observed_process_window?: JsonObject;
  D02_robust_observed_region?: JsonObject;
  D02_supported_region?: JsonObject;
  D03_tradeoffs?: JsonObject;
  D04_experiment_proposal?: JsonObject;
  D05_effectiveness?: JsonObject;
};

const STOP_STATUSES = new Set<P4Status>(["INCONCLUSIVE", "REFUSED", "ERROR"]);

function isObject(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function asObject(value: unknown): JsonObject {
  return isObject(value) ? value : {};
}

function asList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown): string {
  if (value === undefined || value === null || value === "") return "Not provided";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function entries(value: unknown): Array<[string, unknown]> {
  return isObject(value) ? Object.entries(value) : [];
}

function dossierFor(evidence: P4Evidence): Dossier {
  const artifact = asList(evidence.artifacts).find((item) => asObject(item).type === "p4_decision_dossier");
  return asObject(artifact) as Dossier;
}

function chartFromTradeoffs(tradeoffs: JsonObject | undefined): SuiteChartModel | null {
  if (!tradeoffs || !["VALID", "PARTIAL"].includes(text(tradeoffs.status))) return null;
  const objectives = asList(tradeoffs.objective_metrics).map(asObject);
  const values = asList(tradeoffs.pareto_values).map(asObject);
  if (objectives.length < 2 || !values.length) return null;
  const xMetric = text(objectives[0].metric);
  const yMetric = text(objectives[1].metric);
  const points = values.flatMap((value) => {
    const x = asObject(value)[xMetric];
    const y = asObject(value)[yMetric];
    return typeof x === "number" && Number.isFinite(x) && typeof y === "number" && Number.isFinite(y)
      ? [{ x, values: { [yMetric]: y } }]
      : [];
  });
  if (!points.length) return null;
  return {
    schema_version: "suite-chart.v1",
    chart_id: "p4-supported-pareto",
    kind: "scatter",
    title: "Observed Pareto setting means",
    x_label: `${xMetric} (${text(objectives[0].direction)})`,
    y_label: `${yMetric} (${text(objectives[1].direction)})`,
    series: [{ id: yMetric, label: yMetric, style: "markers" }],
    points,
  };
}

function AccessibleChart({ model, renderChart }: { model: SuiteChartModel; renderChart?: P4PanelProps["renderChart"] }) {
  const chart = renderChart?.(model);
  return (
    <section aria-labelledby={`${model.chart_id}-heading`}>
      <h4 id={`${model.chart_id}-heading`}>{model.title}</h4>
      {chart ? <figure>{chart}<figcaption>{model.title}. Exact values and setting identifiers are listed in the table.</figcaption></figure>
        : <p role="status">The shared suite chart renderer is not mounted; the exact data remains available in the table.</p>}
      <details open>
        <summary>Accessible chart data</summary>
        <table>
          <caption>{model.title}: {model.y_label} by {model.x_label}</caption>
          <thead><tr><th scope="col">{model.x_label}</th>{model.series.map((series) => <th scope="col" key={series.id}>{series.label}</th>)}</tr></thead>
          <tbody>{model.points.map((point, index) => <tr key={`${model.chart_id}-${index}`}>
            <th scope="row">{text(point.x)}</th>{model.series.map((series) => <td key={series.id}>{text(point.values[series.id])}</td>)}
          </tr>)}</tbody>
        </table>
      </details>
    </section>
  );
}

function Status({ value }: { value: unknown }) {
  return <span>{text(value)}</span>;
}

function KeyValueTable({ label, value }: { label: string; value: unknown }) {
  const rows = entries(value);
  if (!rows.length) return <p>No values reported.</p>;
  return <table>
    <caption>{label}</caption>
    <thead><tr><th scope="col">Measure</th><th scope="col">Value</th></tr></thead>
    <tbody>{rows.map(([key, item]) => <tr key={key}><th scope="row">{key}</th><td>{text(item)}</td></tr>)}</tbody>
  </table>;
}

function D01Section({ result }: { result: JsonObject | undefined }) {
  if (!result) return <section id="p4-d01"><h3>D01 · Factor sensitivity</h3><p>No D01 result was provided.</p></section>;
  const terms = entries(result.terms);
  return <section id="p4-d01" aria-labelledby="p4-d01-heading">
    <h3 id="p4-d01-heading">D01 · Factor sensitivity</h3>
    <p>Result status: <Status value={result.status} />. Associations describe observed evidence and are not intervention effects.</p>
    <p>{text(result.interpretation || result.reason)}</p>
    <KeyValueTable label="Model terms and uncertainty" value={Object.fromEntries(terms.map(([name, item]) => {
      const term = asObject(item);
      return [name, `estimate ${text(term.estimate)}; 95% interval ${text(term.ci95)}; SE ${text(term.standard_error)}`];
    }))} />
    <KeyValueTable label="Design and identifiability diagnostics" value={result.diagnostics} />
    {asList(result.diagnostic_warnings).length > 0 && <ul aria-label="D01 diagnostic warnings">{asList(result.diagnostic_warnings).map((item, index) => <li key={index}>{text(item)}</li>)}</ul>}
  </section>;
}

function D02Section({ observed, robust, supported }: { observed?: JsonObject; robust?: JsonObject; supported?: JsonObject }) {
  const supportedGrid = asList(supported?.grid).map(asObject);
  const cells = supportedGrid.length ? supportedGrid : asList(supported?.candidate_cells).map(asObject);
  const [regionFilter, setRegionFilter] = useState("all");
  const [feasibleFilter, setFeasibleFilter] = useState("all");
  const [search, setSearch] = useState("");
  const filtered = useMemo(() => cells.filter((cell) => {
    const region = text(cell.region_class);
    const feasible = cell.conservative_feasible === true ? "yes" : cell.conservative_feasible === false ? "no" : "unknown";
    const factorText = JSON.stringify(cell.factors ?? {}).toLowerCase();
    return (regionFilter === "all" || region === regionFilter)
      && (feasibleFilter === "all" || feasible === feasibleFilter)
      && (!search || factorText.includes(search.toLowerCase()));
  }), [cells, feasibleFilter, regionFilter, search]);
  const firstFactors = asObject(cells[0]?.factors);
  const factorNames = Object.keys(firstFactors);
  const metrics = Object.keys(asObject(cells[0]?.predictions));
  return <section id="p4-d02" aria-labelledby="p4-d02-heading">
    <h3 id="p4-d02-heading">D02 · Evidence-supported process window</h3>
    <p>Observed, interpolated, extrapolated, and unsupported areas retain separate labels. A modeled feasible cell is not a production recipe or approval.</p>
    <KeyValueTable label="Observed settings and scope" value={observed} />
    <KeyValueTable label="Robust observed settings" value={robust} />
    <KeyValueTable label="Supported exploration and uncertainty rule" value={supported ? {
      status: supported.status, qualification: supported.qualification, method: supported.method,
      region_counts: supported.region_counts, uncertainty_rule: supported.uncertainty_rule,
      grouped_holdout_calibration: supported.calibration,
      extrapolation_within_approved_bounds_present: supported.extrapolation_within_approved_bounds_present,
    } : undefined} />
    <form aria-label="Filter process-window evidence" onSubmit={(event) => event.preventDefault()}>
      <label>Evidence region
        <select value={regionFilter} onChange={(event) => setRegionFilter(event.currentTarget.value)}>
          <option value="all">All regions</option>
          <option value="observed">Observed</option>
          <option value="interpolated">Interpolated</option>
          <option value="extrapolated">Extrapolated</option>
          <option value="unsupported">Unsupported</option>
        </select>
      </label>
      <label>Conservative feasibility
        <select value={feasibleFilter} onChange={(event) => setFeasibleFilter(event.currentTarget.value)}>
          <option value="all">All</option><option value="yes">Feasible under stated bounds</option>
          <option value="no">Not feasible</option><option value="unknown">Not estimated</option>
        </select>
      </label>
      <label>Search factor settings
        <input value={search} onChange={(event) => setSearch(event.currentTarget.value)} type="search" />
      </label>
    </form>
    <p role="status">Showing {filtered.length} of {cells.length} supported-region cells.</p>
    {cells.length === 0 ? <p>No supported-region cells were returned.</p> : <div>
      <table>
        <caption>Supported process-window cells with local group-held-out calibrated intervals</caption>
        <thead><tr>{factorNames.map((factor) => <th scope="col" key={factor}>{factor}</th>)}<th scope="col">Evidence region</th><th scope="col">Conservative feasibility</th>
          {metrics.map((metric) => <th scope="col" key={metric}>{metric}: estimate and calibrated interval</th>)}</tr></thead>
        <tbody>{filtered.map((cell, index) => <tr key={index}>
          {factorNames.map((factor) => <td key={factor}>{text(asObject(cell.factors)[factor])}</td>)}
          <td>{text(cell.region_class)}</td><td>{cell.conservative_feasible === true ? "Yes under stated limits" : cell.conservative_feasible === false ? "No" : "Unknown"}</td>
          {metrics.map((metric) => {
            const prediction = asObject(asObject(cell.predictions)[metric]);
            return <td key={metric}>{text(prediction.estimate)}; local group-held-out empirical interval (95% order-statistic rank, no conditional coverage guarantee) {text(prediction.predictive_interval95)}; calibration {text(prediction.calibration_status)} across {text(prediction.calibration_units)} independent units; model interval {text(prediction.model_predictive_interval95)} ({text(prediction.status)})</td>;
          })}
        </tr>)}</tbody>
      </table>
    </div>}
  </section>;
}

function D03Section({ result, renderChart }: { result?: JsonObject; renderChart?: P4PanelProps["renderChart"] }) {
  const chart = chartFromTradeoffs(result);
  const rows = asList(result?.candidate_settings).map(asObject);
  const objectives = asList(result?.objective_metrics).map(asObject);
  return <section id="p4-d03" aria-labelledby="p4-d03-heading">
    <h3 id="p4-d03-heading">D03 · Cross-step and multiobjective tradeoffs</h3>
    <p>Status: <Status value={result?.status} />. {text(result?.qualification || result?.reason)}</p>
    <p>Objective directions: {objectives.map((item) => `${text(item.metric)} (${text(item.direction)})`).join("; ") || "not provided"}.</p>
    {chart && <AccessibleChart model={chart} renderChart={renderChart} />}
    <table>
      <caption>Candidate setting means, population size, and observed lineage</caption>
      <thead><tr><th scope="col">Setting</th><th scope="col">Factor values</th><th scope="col">Independent units</th>{objectives.map((item) => <th scope="col" key={text(item.metric)}>{text(item.metric)} mean</th>)}<th scope="col">Pareto status</th></tr></thead>
      <tbody>{rows.map((row, index) => {
        const id = text(row.id);
        const paretoIds = asList(result?.pareto_setting_ids).map(text);
        return <tr key={`${id}-${index}`}><th scope="row">{id}</th><td>{text(row.factors)}</td><td>{text(row.independent_units)}</td>
          {objectives.map((item) => <td key={text(item.metric)}>{text(asObject(row.means)[text(item.metric)])}</td>)}
          <td>{paretoIds.includes(id) ? "On reported Pareto set" : "Not on reported Pareto set"}</td></tr>;
      })}</tbody>
    </table>
    {result?.causal_claim === false && <p role="status">No causal claim is made from these observed tradeoffs.</p>}
  </section>;
}

function D04Section({ result }: { result?: JsonObject }) {
  const runs = asList(result?.runs).map(asObject);
  const factors = asList(result?.factors).map(asObject);
  return <section id="p4-d04" aria-labelledby="p4-d04-heading">
    <h3 id="p4-d04-heading">D04 · Next experiment proposal</h3>
    <p>Status: <Status value={result?.status} />. Proposed runs: {text(result?.run_count)}. Executed: {text(result?.executed)}.</p>
    <p>{text(result?.qualification || result?.reason)} No equipment command is issued by this module.</p>
    <KeyValueTable label="Design and authorization requirements" value={{ design: result?.design, power: result?.power, blocking: result?.blocking,
      authorization_fields: result?.authorization_fields, actuation: result?.actuation, randomization_seed: result?.randomization_seed }} />
    <table>
      <caption>Proposed run order for engineer review</caption>
      <thead><tr><th scope="col">Run order</th><th scope="col">Block</th><th scope="col">Replicate</th>{factors.map((factor) => <th scope="col" key={text(factor.name)}>{text(factor.name)}</th>)}</tr></thead>
      <tbody>{runs.map((run, index) => <tr key={`${text(run.run_order)}-${index}`}><th scope="row">{text(run.run_order)}</th><td>{text(run.block)}</td><td>{text(run.replicate)}</td>
        {factors.map((factor) => <td key={text(factor.name)}>{text(run[text(factor.name)])}</td>)}</tr>)}</tbody>
    </table>
  </section>;
}

function D05Section({ result }: { result?: JsonObject }) {
  if (!result) return <section id="p4-d05"><h3>D05 · Change effectiveness</h3><p>No D05 result was provided.</p></section>;
  const diagnosticRows = entries(result.diagnostics).map(([name, value]) => [name, text(value)] as const);
  return <section id="p4-d05" aria-labelledby="p4-d05-heading">
    <h3 id="p4-d05-heading">D05 · Change effectiveness</h3>
    <p>Status: <Status value={result.status} />. Study design: {text(result.design)}. Estimate: {text(result.estimate)}.</p>
    <p>{result.causal_claim === true ? "A conditional causal interpretation is reported with its stated assumptions." : "Causal interpretation is withheld; this estimate is not presented as causal."}</p>
    <KeyValueTable label="Uncertainty and sensitivity" value={{ standard_error: result.se, ci95_welch_t_approximation: result.ci95_welch_t_approximation,
      welch_degrees_of_freedom: result.welch_df, sensitivity: result.sensitivity, attrition: result.attrition, baseline_balance: result.baseline_balance }} />
    <table>
      <caption>Study diagnostics and counterevidence</caption>
      <thead><tr><th scope="col">Diagnostic</th><th scope="col">Result</th></tr></thead>
      <tbody>{diagnosticRows.map(([name, value]) => <tr key={name}><th scope="row">{name}</th><td>{value}</td></tr>)}</tbody>
    </table>
    <KeyValueTable label="Assumptions and qualification limits" value={result.assumptions || result.qualification} />
  </section>;
}

/** Headless P4 analysis module. Route, design tokens, request lifecycle, and chart runtime belong to the shared workspace. */
export function P4Panel({ sourcePreview, evidence, charts = [], renderChart }: P4PanelProps) {
  const blocked = Boolean(evidence && STOP_STATUSES.has(evidence.status));
  const dossier = evidence ? dossierFor(evidence) : {};
  const paretoChart = chartFromTradeoffs(dossier.D03_tradeoffs);
  return <article className="p4-panel" aria-labelledby="p4-panel-title" data-product-id="p4">
    <header>
      <h2 id="p4-panel-title">FAB Process Improvement Intelligence</h2>
      <p>Review process sensitivity, supported windows, tradeoffs, experiment proposals, and change evidence.</p>
      {sourcePreview.status === "SYNTHETIC_ONLY" && <p role="status">Synthetic demonstration data only</p>}
    </header>
    <section aria-labelledby="p4-source-title">
      <h3 id="p4-source-title">Source and population</h3>
      <dl><dt>Source status</dt><dd>{text(sourcePreview.status)}</dd><dt>Permission</dt><dd>{text(sourcePreview.permission)}</dd>
        <dt>Semantic version</dt><dd>{text(sourcePreview.semantic_version)}</dd><dt>Observation grain</dt><dd>{text(sourcePreview.grain)}</dd>
        <dt>Metric and unit</dt><dd>{text(sourcePreview.metric)} ({text(sourcePreview.unit)})</dd><dt>Scope</dt><dd>{text(sourcePreview.scope)}</dd>
        <dt>Time window</dt><dd>{text(sourcePreview.time_window)}</dd>
        {Object.entries(sourcePreview.coverage ?? {}).map(([key, value]) => <Fragment key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{text(value)}</dd></Fragment>)}
      </dl>
    </section>
    {!evidence ? <p role="status">No analysis result is available. The shared workspace owns request, retry, and cancellation controls.</p> : <>
      <section aria-labelledby="p4-result-status" aria-live="polite">
        <h3 id="p4-result-status">Analysis status</h3><p><strong>{evidence.status}</strong> · Investigation <code>{evidence.investigation_id}</code></p>
        {blocked ? <p role="status">Positive findings and charts are withheld because this result is {evidence.status.toLowerCase()}.</p> : <ul>{evidence.claims.map((claim, index) => <li key={`${claim.method ?? "claim"}-${index}`}>
          <p>{claim.statement}</p><p>Claim type: {text(claim.category)}. Certainty: {text(claim.certainty)}. Method: {text(claim.method)}.</p>
        </li>)}</ul>}
        <KeyValueTable label="Assumptions and counterevidence" value={{ assumptions: evidence.assumptions, counterevidence: dossier.counterevidence }} />
        <h4>Limitations</h4>{evidence.limitations.length ? <ul>{evidence.limitations.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul> : <p>No limitations reported.</p>}
      </section>
      {!blocked && <nav aria-label="P4 evidence sections"><h3>Evidence navigation</h3><ul>
        {["D01 Factor sensitivity", "D02 Process window", "D03 Tradeoffs", "D04 Experiment proposal", "D05 Change effectiveness"].map((label, index) => <li key={label}><a href={`#p4-d0${index + 1}`}>{label}</a></li>)}
      </ul></nav>}
      {!blocked && <>
        <D01Section result={dossier.D01_sensitivity} />
        <D02Section observed={dossier.D02_observed_process_window} robust={dossier.D02_robust_observed_region} supported={dossier.D02_supported_region} />
        <D03Section result={dossier.D03_tradeoffs} renderChart={renderChart} />
        <D04Section result={dossier.D04_experiment_proposal} />
        <D05Section result={dossier.D05_effectiveness} />
        {charts.map((chart) => <AccessibleChart key={chart.chart_id} model={chart} renderChart={renderChart} />)}
        {paretoChart && <details><summary>Shared chart model for the suite renderer</summary><pre>{JSON.stringify(paretoChart, null, 2)}</pre></details>}
      </>}
      <section aria-labelledby="p4-provenance-title">
        <h3 id="p4-provenance-title">Evidence provenance</h3>
        {evidence.provenance?.input_sha256 && <p>Input SHA-256: <code>{text(evidence.provenance.input_sha256)}</code></p>}
        {evidence.provenance?.engine_version && <p>Engine: <code>{text(evidence.provenance.engine_version)}</code></p>}
        {evidence.provenance?.method_version && <p>Method: <code>{text(evidence.provenance.method_version)}</code></p>}
        {evidence.sources?.length ? <ul aria-label="Evidence sources">{evidence.sources.map((source) => <li key={source.id}>
          <code>{source.id}</code>{source.grain && ` — ${source.grain}`}{source.source_hash && ` — SHA-256 ${source.source_hash}`}
        </li>)}</ul> : <p>No source references reported.</p>}
      </section>
      {!blocked && <details><summary>Inspect complete evidence envelope</summary><pre>{JSON.stringify(evidence, null, 2)}</pre></details>}
    </>}
  </article>;
}
