# Corrected candidate and integration gates

The initial local qualification below was superseded during independent merge
review. `99f069875` fixes a real JWKS cache bug: cached-key reuse now preserves
the original deadline, including when a callback completes after cache expiry.
The new regression fails on the old implementation and all **27 PostgreSQL
tests** pass with the correction. The auth reviewer found no remaining blocker.

`f1bd2ea98` isolates fork CI. All **125 inherited jobs in 58 workflows** require
the exact upstream repository, preventing upstream publication, deployment,
automatic merging and source pushback in this fork. Fork qualification runs on
PRs, manual dispatch and pushes to `develop`. Update automation retains the
fork's workflow tree before pushing candidates; its added/changed/deleted
workflow-retention regression passes. An independent CI reviewer cleared these
changes. Hosted runs still own final merge acceptance.

The corrected local runtime image is
`sha256:28e2769e3c6e4d3458ad211665ad05c200f2e13bc07fed7aac5c11b6d33708dc`,
built from `f1bd2ea98dd59c28427abcd0c5d3fe218cbfbfc3`; later integration and
measurement-harness commits retain identical runtime inputs. The new local
candidate passes the two-user stock editor/account/CSRF/draft/service suite,
three auth-hook tests, native credential/lifecycle/revoke/logout checks, real
provider outage and signing-key rotation. The earlier two focused editor tests
cover unchanged frontend source; the complete upstream suite is not claimed.

The new local full-duration removal measurements are **unqualified**: sampling
gaps exceeded the nominal five-second cadence, and one run returned 200 after a
large gap at 691 seconds on the host monotonic clock. The cause has not been
established. The test now records its clock and largest observed sampling gap,
probes after resuming before checking timeout, bounds provider control requests,
and emits redacted phase/status diagnostics. Do not infer a successful removal
bound from these runs. A fresh hosted Linux qualification must pass the full
300-second removal, callback, lifecycle and restore sequence before merge.

The user explicitly selected **Community 1.23.2** as the fork baseline and
**develop** as its default/integration branch. The integration deliberately
replaces the inherited development tree while preserving published history
through a normal PR. It does not port to upstream development HEAD, rewrite
history, activate paid features or deploy a production instance.

The fork has issues disabled; the supplied Keycloak fork specification is the
acceptance contract. Production remains unqualified. A green merge gate does
not claim project isolation, blind review, immediate global logout, canonical
publication, audio/video acceptance or eight-hour endurance.
