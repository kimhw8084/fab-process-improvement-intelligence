# Authorized company-side qualification and OpenCode onboarding

**Do not connect to an actual company system until the appropriate site owner has approved the exact read-only test.** `python -m fabintel preflight` is local and reports PENDING. `python -m fabintel mcp-test` contacts only the bundled synthetic server and is the externally testable protocol check.

Use this sequence from the unpacked P4 folder. The same commands can be run from an OpenCode terminal; OpenCode may help edit a site-owned draft, but deterministic tools produce diagnostics and never approve mappings.

1. Obtain source-owner approval for the exact read-only discovery, semantic query, row limit, and source allowlist. Verify the archive checksum, independent review, license/security reports, and approved target OS before transfer.
2. Install offline on that confirmed OS. Keep credentials in approved environment variables; never put secret values in JSON, prompts, logs, or source.
3. The site owner fills a copy of `requirements/company-config.template.json` using real MCP discovery output and the approved semantic catalog. Do not copy synthetic mappings as real mappings. The frozen logical operation contract is `contracts/adapter-operations.v1.json`. D01–D05 also require explicit normalization, units, context, population grain, source versions, and approved time bounds. Only one source or an approved two-source relationship is supported.
4. Run the zero-connection structural check:

   ```bash
   python -m fabintel mcp-config-validate --config <site-config> --output config-review.json
   ```

   `STRUCTURALLY_VALID_REVIEW_REQUIRED` means local shape/consistency passed; it does not authenticate authorization or semantics. Repair every reported error before connecting.
5. After the site owner authorizes discovery/semantic inspection, create an unapproved deterministic review:

   ```bash
   python -m fabintel mcp-onboard --config <site-config> \
     --site-approval-reference <approved-ref> --authorized-site-test \
     --draft-config-output <separate-review-copy> \
     --output onboarding-review.json
   ```

   The separate draft remains `PENDING_INTERNAL`; it is never signed or qualified. For synthetic-only qualification, use `--synthetic-test` instead of the internal authorization flags. Exact identifier/unit suggestions remain proposals. An authorized semantic owner must independently inspect the catalog, mappings, grain, units, relationship, permission, and experiment context; the LLM and this command cannot sign the review.
6. After written site review, populate the site's approved qualification inputs and obtain a nonempty site approval reference. Re-run structural validation, then run the bounded test:

   ```bash
   python -m fabintel site-mcp-qualify --config <site-config> \
     --site-approval-reference <approved-ref> --authorized-site-test \
     --output site-qualification.json
   ```

   `SITE_TESTS_COMPLETED_PENDING_SIGNOFF` is not company approval. The source owner must inspect the audit record and sign the local qualification outside P4. Only after that owner-controlled step may `qualification_status` be set to `QUALIFIED_INTERNAL`.
7. Start the standalone application with the reviewed config:

   ```bash
   python -m fabintel serve --mcp-config <site-config>
   ```

   Open the loopback URL printed by the command and use **Run configured read-only investigation**. Check the acquisition audit, D01–D05 results, uncertainty, refusals, and exported evidence before engineering use. P4 has no recipe-write or equipment-control operation.
8. For diagnostics, rerun `mcp-config-validate`, `mcp-onboard`, and the authorized qualification step after any mapping or server change. Keep reports local and redact company identifiers before external escalation. On failure, stop the server with Ctrl-C, retain the diagnostic output for the site owner, restore the backed-up reviewed config, or remove `--mcp-config` to return to local-only operation. Never weaken source, unit, relationship, time-window, or read-only checks to clear an error.

Company-specific endpoints, source permissions, semantic mappings, target OS, deployment host, authenticators, accepted source definitions and ROI baselines **remain pending internal verification**. Site operators must discover and explicitly configure them; this package invents none. Company authorization and production approval are not established by synthetic tests or local reports.
