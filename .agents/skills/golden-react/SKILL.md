---
name: golden-react
description: Build or verify P4's headless React panel against the single P1-owned FAB workspace contract
---

# React suite module

1. P1 owns the suite shell, routes, design tokens, request lifecycle, and shared chart renderer. P4 exports `P4Panel` and does not create a product shell or separate design system.
2. Follow `suite-ui-module.v1`, `suite-chart.v1`, and evidence envelope v1.0.0. Compare against the actual P1 contract before integration; record schema gaps instead of changing an external owner contract locally.
3. Use the host's React, semantic HTML tables, and host chart callback. Add no chart framework, table grid, CSS token set, or component library to P4.
4. Make source scope, uncertainty, limitations, and provenance inspectable. Refused or inconclusive evidence must not show positive claims. Keep scientific chart values available in accessible tables.
5. Verify keyboard interaction, labels, focus, empty/error/refusal states, and exact evidence data. Browser and target-host qualification require the actual shared host and staged assets.
