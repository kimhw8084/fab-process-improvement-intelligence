# D04 optimization comparison and retention decision

Qualification record: 2026-11-22. Seeded protocol and full metrics are in `release/D04_OSS_COMPARISON.json`; the reproducible script is `qualification/benchmark_d04_oss.py`.

The qualification environment pins scikit-learn 1.5.2. The previous 1.2.2 pin was found by dependency audit to match CVE-2024-5206 and was updated; the full resolved benchmark dependency tree then had zero known package advisories. The audit is recorded at `release/DEPENDENCY_AUDIT.json`.

## Compared alternatives

- SciPy `qmc.LatinHypercube` plain and `optimization="random-cd"` for the same 32-run, four-factor, 64-seed sampling task. SciPy describes random-cd as a centered-discrepancy optimizer and cautions that post-processing may not preserve every sample property. [SciPy LatinHypercube docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.qmc.LatinHypercube.html)
- pyDOE3 `optimal_design(..., criterion="D", method="detmax")` on the exact same 3-by-3 candidate grid and first-order model, with exhaustive enumeration of all 84 six-run designs as an independent optimum. [pyDOE3 optimal-design docs](https://pydoe3.readthedocs.io/en/stable/reference/doe_optimal/)
- scikit-optimize GP expected improvement versus P4's cluster-robust quadratic EI on fixed smooth-quadratic, asymmetric-quadratic, and multimodal response functions. The algorithm family and assumptions follow its published example. [scikit-optimize Bayesian optimization docs](https://scikit-optimize.readthedocs.io/en/latest/auto_examples/bayesian-optimization.html)

## Results and product decision

- P4 basic LHS exactly stratified every factor margin in all 64 seeds. Its mean centered discrepancy was 0.00776; SciPy basic was 0.00792. SciPy random-cd improved mean discrepancy to 0.00310 and mean maximum absolute correlation from about 0.295 to 0.039. P4 makes no claim to beat an optimized LHS. The portable basic LHS remains a standard space-filling option; no SciPy dependency or copied optimization code is included.
- P4 greedy D-optimal achieved 100% of the enumerated optimum in the fixed case, matching pyDOE3 detmax. Seeded random designs averaged 80.50% of the optimum. pyDOE3's own reported `D_eff` uses a different normalization; the direct comparison is recomputed from the same `X'X` determinants.
- Before grouped-validation refusal was added, P4 EI lost to scikit-optimize on the asymmetric and multimodal cases. The final protocol uses 32 seeds for each fixed function, a 41-point P4 candidate grid, five-fold independent-unit validation, and an engineer-specified maximum RMSE of 0.10. P4 accepted both quadratic functions (64/64 cases), with mean true-function regret 0.0000375 and lower regret than scikit-optimize in 76.6% of those paired accepted cases. It refused all 32 multimodal cases because grouped CV error exceeded the stated limit. This demonstrates a narrow, validated use case and a meaningful refusal boundary; it does not establish general superiority to Bayesian optimization.
- Benchmark-only dependencies are pinned in `qualification/benchmark-requirements.txt`. The released product runtime remains Python standard library only. This is a portability choice, not a finding that the benchmark libraries are inferior.

These synthetic fixed-function results qualify algorithm behavior only. They do not establish wafer-level performance, target-host suitability, or engineering ROI.
