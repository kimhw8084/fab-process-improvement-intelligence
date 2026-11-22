# P4 candidate install, stop, and rollback

This candidate has no background daemon, installer service, equipment command, recipe write, or persistent database.

## Fresh offline install

1. Verify `TRANSFER_BUNDLE.sha256` using the platform SHA-256 utility.
2. Extract `FAB_INTELLIGENCE_P4_CANDIDATE.zip` into a new, empty directory.
3. From that directory, run `python bootstrap_check.py`, then `python -m fabintel doctor`.
4. No `pip`, `npm`, network registry, license server, or runtime download is required. Python 3.10+ is a prerequisite supplied by the site, not bundled with this ZIP.
5. Do not configure real company sources in this synthetic-only candidate.

## Stop and cancel

- Stop the foreground UI/API server with `Ctrl-C`. Shutdown sets the cancellation event for every active analysis job, then closes the listener.
- During UI analysis, use **Cancel analysis**. It sets the job cancellation event. The engine checks that event during input validation, OLS diagnostics, Pareto evaluation, process-window filtering, and DOE generation.
- If the server does not respond, terminate only the foreground `python -m fabintel serve` process launched for this candidate. There are no child workers outside that process; analysis threads are daemon threads and no request is persisted.
- This candidate has no actuation route. The actuation test case requires refusal and an empty claims list.

## Rollback

Close the server, then delete only the isolated extraction directory created for this candidate. There is no system-wide installer, service, company data store, or semantic catalog to revert. Preserve the original archive and checksum if audit evidence is needed. Do not point the extraction directory at an existing company application directory.

## Qualification status

The loopback server and cancellation endpoint are locally tested. The user organization's OS, approved host, service management, and actual internal rollback policy are unknown and remain pending internal qualification.
