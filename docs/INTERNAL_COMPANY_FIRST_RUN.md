# P4 authorized internal first run

## One-instruction start

Extract the approved package, open the folder in the approved internal OpenCode build using the company-approved local/internal model, and send:

> `@p4-internal-onboarding Start P4 onboarding from this extracted folder. Complete all local checks and prepare a PENDING_INTERNAL draft. Ask only for missing essential inputs: the exact source-owner approval for metadata discovery or bounded read-only qualification, and the engineer's objective, approved factor bounds, metric definitions, and process context.`

OpenCode loads `.opencode/skills/p4-internal-onboarding/SKILL.md` from the project folder. The skill is also mirrored under `.agents/skills/` for Codex-compatible discovery. For CLI startup, set `OPENCODE_DISABLE_AUTOUPDATE=1` and `OPENCODE_DISABLE_MODELS_FETCH=1`; these reduce automatic requests but do not replace the company's OS-enforced egress policy. Do not load the skill from an unverified source folder.

## Deterministic fallback commands

Run from the extracted folder on the approved target OS:

```bash
python qualification/first_run.py --output qualification/first-run.json
python -m fabintel doctor
python -m fabintel preflight
```

For metadata discovery, copy `requirements/mcp-discovery.template.json`, configure only the owner-supplied transport/host/credential-variable reference and approval ID, then obtain explicit approval for `initialize` and `tools/list`:

```bash
python -m fabintel mcp-discover --config <discovery-config> \
  --site-approval-reference <approved-reference> --authorized-discovery \
  --draft-config-output <separate-partial-draft.json> --output <local-capabilities.json>
```

Discovery does not invoke manufacturing tools. Its exact-name and complete-schema matches remain proposals. Local schema validation must still reject the partial draft until an administrator-authorized semantic catalog, reviewed operation mappings, engineer objective/context/units/bounds, grain, population and time semantics are present.

After independent semantic-owner review, run `mcp-config-validate`, then `mcp-onboard` to generate a separate unapproved normalization review. Only after explicit bounded-read approval run `site-mcp-qualify`. A report ending `PENDING_SIGNOFF` is not internal qualification; the owner alone records the signed decision. Start the UI with `python -m fabintel serve --mcp-config <owner-signed-config>`. Rollback by stopping the foreground process, restoring the reviewed config, and restarting without `--mcp-config`.

Company endpoints, grants, semantic meanings, source relationships, target OS, OpenCode policy, actual data, engineer acceptance, ROI, and legal/security signoff remain company-controlled. No synthetic evidence changes those statuses.
