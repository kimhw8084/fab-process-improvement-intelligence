# P1 shared focus-indicator change proposal

**Owner:** P1 shared shell. This is an additive proposal against a disposable, caller-supplied snapshot; no authoritative P1 source was modified.

The selected CSS screen found the supplied shared `:focus-visible` outline `#eeaf39` below its 3:1 non-text screening value on the body (1.804), module card (1.940), and navigation (1.940) backgrounds. A disposable proposal stylesheet changed the rule to:

```css
.button:focus-visible, a:focus-visible, summary:focus-visible, input:focus-visible, select:focus-visible {
  outline: 2px solid #ffffff;
  outline-offset: 2px;
  box-shadow: 0 0 0 5px #142b3d;
}
```

The source-level screen found the dark outer ring above 13:1 against those sampled surfaces. This does not establish rendered indicator area, browser cascade, keyboard workflow, zoom/reflow, high-contrast behavior, assistive-technology support, or WCAG conformance.

**Acceptance on authoritative P1:** apply or replace the suite-owned focus token/rule; verify visible focus for navigation, buttons, links, inputs, selects, and disclosure summaries by keyboard; test responsive layout and zoom; run the P1 owner’s accessibility checks and record the exact source revision. P4 remains headless and does not add a competing focus system.

**Status:** PENDING_AUTHORITATIVE_P1_OWNER. Evidence: `qualification/results/P1_SHARED_UI_CONTRAST_SCREEN.json` and `qualification/results/P1_SHARED_UI_FOCUS_PROPOSAL_SCREEN.json` (disposable, source-level screens only).
