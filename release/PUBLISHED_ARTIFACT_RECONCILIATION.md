# Published candidate artifact reconciliation

Date: 2026-11-22. This record is read-only evidence about the prior candidate commit; it does not authorize another publication.

## Verified artifact

- GitHub repository: `kimhw8084/fab-intelligence-p4`, currently private.
- Default branch HEAD: `d16ec28fef00541cbd11b79a5b29b4bf9bf2672e` (`origin/main` matched this full commit).
- The GitHub tree at that commit contains `release/FAB_INTELLIGENCE_P4_CANDIDATE.zip`, size 126,900 bytes, Git blob SHA-1 `53665dd79a11075efc66805926214a7aafe1123c`.
- The local archive has the same Git blob SHA-1, proving its bytes match the archive tracked at that commit.
- SHA-256 of those bytes: `97d36ffe6e23b5af5e4b724e84a097f28682a911d834cdbbc545a07660aeda64`.
- The committed `release/TRANSFER_BUNDLE.sha256` contains the same SHA-256. `release/BUILD_REPRODUCIBILITY.json` records two deterministic builds with that same digest.
- GitHub Releases API returned no release entries or release assets. The artifact was published as a file in the repository commit, rather than as a GitHub Release asset.

## Conflicting digest

The alternate report preserved in the continuation context was only the prefix `104d66e8…`. That prefix is not present in the candidate commit's transfer sidecar or reproducibility report, and its full digest and input artifact were not preserved. It cannot be reproduced or attributed to the tracked ZIP. It is therefore unverified and must not be used for this artifact. For the exact bytes tracked at `d16ec28`, `97d36ffe…` is the verified SHA-256.

A different SHA-256 would imply different bytes or a reporting error; it cannot be a second valid SHA-256 for this same archive.

## Scope

This reconciles the old candidate archive only. It does not qualify the changed local implementation, grant distribution rights, confirm source ownership, establish company approval, or authorize a new upload. Those gates remain pending.
