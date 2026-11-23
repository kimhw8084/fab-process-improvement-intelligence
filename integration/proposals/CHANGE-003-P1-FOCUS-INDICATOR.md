# CHANGE-003 — P1 shared focus indicator contrast

**Status: P1 owner review pending. This is a measured P4-side proposal, not a host change or accessibility approval.**

## Evidence

The scoped source checker evaluated the caller-supplied P1 stylesheet at SHA-256 `d1d80dd866d85d02003b1a48bdd1a3cbd8e4bd16432eae1e39ab0ec0f1e44c81`. Six selected text pairs met the checker’s 4.5:1 screening value. The declared keyboard outline `#eeaf39` measured:

| Adjacent host surface | Ratio | Screen result |
| --- | ---: | --- |
| Suite page `#f4f7fa` | 1.804:1 | Below 3:1 screening value |
| P1 module card `#ffffff` | 1.940:1 | Below 3:1 screening value |
| P1 navigation `#ffffff` | 1.940:1 | Below 3:1 screening value |
| P1 header `#12334b` | 6.763:1 | Above 3:1 screening value |

The source check is not a rendered cascade audit or WCAG verdict. WCAG 2.2 SC 1.4.11 specifies 3:1 against adjacent colors for applicable author-styled component/state indicators; SC 2.4.13 separately defines a larger focus-area and focused/unfocused contrast test at Level AAA. The ratios above screen only the listed source declarations and do not evaluate those full criteria. See the [W3C Understanding Non-text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html) and [W3C Understanding Focus Appearance](https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html).

A read-only browser check against the disposable P1 snapshot also verified:

- `POST /api/analyze/p4` completed the synthetic workflow and rendered D01–D05 evidence in the P1-owned suite shell.
- The observed Pareto chart had its exact values available through the adjacent accessible table.
- `Run permission refusal check` returned `REFUSED`; source preview reported `NOT_ACCESSED`, the panel said fixture values were suppressed, and positive findings/charts were withheld.
- Keyboard focus reached the host provenance disclosure. Pressing Enter expanded it and exposed the route and fixture SHA-256 in the accessibility tree.
- No operating-system screen reader or formal accessibility audit was run. This disposable snapshot does not establish P1 owner approval or target-host behavior.

## Requested host-owner action

Please review a shared focus treatment that remains visible on both the light suite surfaces and the dark P1 header. A two-tone indicator is one candidate for evaluation; P1 should own the final token and implementation. Verify it on every focusable control and chart/table interaction at supported viewport sizes, including its geometry, adjacent colors, clipping, zoom, and high-contrast modes. Run the approved keyboard and screen-reader workflow in the authoritative host before closing the accessibility gate.

P4 does not change P1 CSS. P1 remains the owner of the shared shell and its accessibility contract.
