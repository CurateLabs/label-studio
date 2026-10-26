# Community Keycloak qualification record

Local qualification on 2026-10-26 UTC uses synthetic contributors/documents,
real Keycloak, PostgreSQL, HTTPS, the stock rebuilt editor, Docker Compose and
an isolated single-node Kubernetes cluster. No production realm, production
deployment or paid resource was changed. **Production remains unqualified**:
repeat acceptance against the actual immutable deployment, realm, ingress,
storage, network boundaries and operating procedures before opening access.

## Immutable candidate

| Item | Exact revision |
| --- | --- |
| Upstream Community | `1.23.2`, `df96d79183156e556d91825d15fa7721f1145e1a` |
| Image build source | `65445d4d17a455a20f62a21605b519fff356edf7` |
| Candidate OCI index | `sha256:7c3d1b4c7f72597a604bf20e4403341ce15d9f3dac68d40e2d306979720b07bb` |
| Tested linux/arm64 manifest | `sha256:319bc18d816687c4dd7ba0bca77c44b8f235c9dbc416fafce78a1462228fb3b9` |
| Image configuration | `sha256:792dbc638eeb905b1179067211cbc3f04cff9be996278e2b41d4c8c7d0be045e` |
| Upstream base index | `sha256:afcc516a22775a39d0d66f4c2ddc95d01be3e3d3862b21fcf4f9de34b4ad4e12` |
| Authlib / joserfc | `1.9.1` / `1.7.7`, BSD-3-Clause |
| Python / Django / DRF | `3.13.15` / `5.2.17` / `3.17.2` |
| cryptography / native SDK | `50.0.1` / `2.1.2` |
| Keycloak / PostgreSQL / Caddy | `26.8.1` / `17.11` / `2.11.1` |
| Browser / Playwright | Chrome `155.0.8059.86` / `1.58.2` |

[release.json](release.json) records source/lock/image correspondence. Subsequent
qualification-harness, documentation and evidence commits do not change the
runtime image inputs; `image_sources_match_fork_sha` is true. The recorded dirty
worktree at capture contains those harness/evidence changes. The source base's
labels match 1.23.2 and its upstream commit, but its installed `label-studio`
Python distribution reports **1.23.0**. This discrepancy is retained explicitly
in [candidate-packages.json](candidate-packages.json), alongside the full runtime
package inventory and [candidate-apk.txt](candidate-apk.txt).

Inputs are digest/hash locked and the frontend is rebuilt from its Yarn lock.
Reproducible inputs do not assert identical rebuild timestamps or provenance.
The native-platform archive imported into kind repackages the transport OCI
index; its manifest/configuration remain the tested digests above. The image
has not been published to a registry or promoted through a production path.
New code is Apache-2.0; upstream LICENSE/NOTICE are preserved.

## Effective test environment

[effective-config.json](effective-config.json) records the public test contract:
issuer `https://keycloak.localhost:8443/realms/labeling`, client `label-studio`,
group `/verdant/labeling/shared`, native organization **1**, separate
`labels.localhost:8443` browser and `machine.localhost:8443` API origins.
Alice and Bob bind to native user IDs **2** and **3**; the registered service
account is **4**. UUID subjects in this artifact belong only to the generated
test realm. Credentials, cookies, dumps and image archives remain in ignored
private storage and are excluded from the Docker build context and evidence.

Backend TLS verification remains enabled with the local CA. The isolated
browser context tolerates this test-only CA. T3 preview could not load the local
certificate (`chrome-error://chromewebdata/`, then `ERR_CERT_AUTHORITY_INVALID`),
so the repository's Playwright workflow used installed Chrome. No trace/HAR or
provider token response is retained. The screenshot uses only synthetic pages.

## Executed checks

| Check | Observed result |
| --- | --- |
| `manage.py test verdant_ls.tests --noinput`, final candidate/PostgreSQL | **26 passed** |
| `node --test deploy/oidc/browser/auth-hooks.test.cjs` | **3 passed** |
| Native editor Jest filter `draft failure recovery` | **2 passed**, 3323 tests skipped; not the complete upstream suite |
| `browser/qualify.cjs`, Kubernetes and Compose | Real two-user SSO, denied admission, stock editor, authors/export, draft renewal, service, native profile/avatar CSRF and logout |
| `browser/lifecycle.cjs`, Kubernetes | Actual native Token/JWT/PAT/refresh rejection, slow upload, revoke/re-enable, absolute deadline and provider logout |
| `browser/outage.cjs`, Kubernetes | Valid local lease works offline; expired lease stays 401; provider restart retains SSO/native ID |
| `browser/key-rotation.cjs`, Kubernetes | Real RS256 signing-key change followed by accepted signed callback with stable native ID; test key removed |
| `browser/provider-removal.cjs` | Full configured 300-second lease, 5-second polling, renewal group denial |
| `browser/restart.cjs`, Kubernetes and Compose | Live session/cookie and identity/annotation/membership/media/key state preserved |
| Compatible-image rollback and isolated restore | See evidence and boundaries below |

The 26 tests exercise actual Authlib token parsing with generated RSA signatures:
wrong issuer/audience/authorized party, expiry/issued-at/not-before, missing or
mismatched nonce, an otherwise valid unsecured token, unknown-key refresh,
discovery issuer/timeouts, state replay, concurrent callback consumption and
concurrent first login. They also cover email rename/collision/recycling,
explicit existing-user linking and protected owner/service users, removed
membership, disabled/re-enabled users, session rotation/generation, CSRF on a
native exempt route, blocked legacy routes, credential/header conflicts,
service access, author spoofing, stale-tab cookies and result-acceptance rollback
after expiry or another tab's logout. UserInfo is never called.

[routes.json](routes.json) contains **704 resolved routes**, including the machine
URL namespace. Native token-specific authenticator classes remain visible in
this inventory, but their routes are blocked and replay tests reject actual
issued native credentials. The session-protected token-settings read returns both token types disabled so
the stock account page can render; settings writes remain blocked. Global DRF
uses the bridge authenticator; any newly
introduced endpoint authenticator fails closed pending review. Ingress strips
untrusted identity headers and request-bearing credential logs are disabled.

The real browser run creates distinct native annotations for both contributors,
updates through the stock editor, and exports Unicode transcription, typed
boxes, classifications and reading-order relations. The service import records
the service actor. See [native-export.json](native-export.json),
[editor-export.json](editor-export.json), [service-import.json](service-import.json)
and [editor.png](editor.png). The live account tests wait for the stock profile
section, save a native profile field and upload/delete a valid avatar under
CSRF protection, with no human-token navigation or account page errors. The expiry screenshot shows the in-memory draft;
renewal in a second tab followed by explicit retry commits it. No mutation is
automatically replayed. Fixture source/page digests, coordinates and rendering
mapping live in `fixtures/oidc`; page images provide the document surface.

## Measured session and removal behavior

The configured authentication lease is **300 seconds**, capped by verified
token expiry, with a **28800-second absolute deadline** preserved across
renewal. Initial cookie expiry was observed at approximately 28798–28799 seconds.
The absolute cutoff is tested with a two-second accelerated deadline, rather
than an eight-hour wall-clock endurance run. Neither an old cookie nor an old
token extends an expired lease. Removal measurements and polling uncertainty
are recorded in [provider-removal.json](provider-removal.json): last 200 at
**297.283 seconds**, first 401 at **302.321 seconds** after group removal,
with **5-second polling**. The observed boundary lies between those samples;
302.321 seconds is not an exact server lease duration. Renewal then rejects
the removed group. Local revoke's first checked protected API returns 401 in
**11 ms** in the final run; the recorded interval starts after
command completion and is not a universal latency guarantee. Re-enabling the
user leaves that old cookie invalid. See [lifecycle.json](lifecycle.json).

A real slow multipart upload spanning an accelerated lease returns 401 without
a committed `FileUpload`. Database writes are rolled back at access acceptance.
This does not establish distributed rollback of remote side effects or promise
cleanup of all orphaned files. During actual provider outage, unexpired work is
allowed and expired work stays blocked. See [provider-outage.json](provider-outage.json).
Live key rotation passes; [key-rotation.json](key-rotation.json) distinguishes
that observation from the protocol test proving exactly one forced JWKS refresh.

## Persistence, migration and rollback

[kubernetes.json](kubernetes.json) records Kubernetes **v1.34.11**, pinned
Calico **3.33.0** and NGINX **1.15.1**, successful candidate migration jobs,
bound media PVC and actual image IDs. Final-image TCP probes show an unrelated
namespace cannot connect to the app service while the ingress namespace can.
These are ingress-policy probes, not a complete production network assessment.
The local kubectl client is 1.32.2, outside supported server minor-version skew;
the executed operations succeeded, but use a supported client for production.

[restart-kubernetes.json](restart-kubernetes.json) and
[restart-compose.json](restart-compose.json) compare hashes of the complete
native binding/annotation/task/membership/media state and secret-key digest,
and verify the same live cookie/native user after restart without reauthenticating.
Compose and Kubernetes use the same database/image/settings. Their media volumes
are separate during the local cutover; writers are quiesced and the newer PVC
is copied back before restoring Compose ingress.

The isolated migration test unapplies/reapplies only bridge schema in a disposable
test database and preserves a pre-existing native user's ID, token and annotation
ownership. Production rollback keeps the additive bridge schema. A retained
compatible candidate is exercised without reverting schema or using the public
password profile; the current image is restored afterward. This is local
compatibility evidence, not a production rollback approval or a promise of
compatibility with arbitrary upstream images.

[rollback-kubernetes.json](rollback-kubernetes.json) records both directions.
The retained candidate source is `96fea5bcd1efe9dae8910e50fdcea8f8769149ed`,
platform manifest `sha256:a6fae032353012bb72cfeb970cc91a8ece90848214e667990dd6afb936af1907`,
configuration `sha256:9494cb11ae456996de468f3fc4bc6b7473aaac0830afe5449b395aec00cda982`.
Recreate deployment permits temporary unavailability; the test waits for
ingress convergence and then checks session/state, rather than claiming zero
downtime.

[restore.json](restore.json) records a coordinated DB/media/key snapshot restored
into a **new** private database and volume. The source is retained. Binding IDs,
native annotations/tasks/memberships, media hashes and key match; restored
sessions/login transactions are zero and all human generations increment.
The final restore preserves **100 annotations, 67 tasks and 75 media files**,
with native binding IDs **2 and 3** unchanged. This tests Label Studio recovery. Persistent Keycloak restart is tested separately;
a coordinated identity-provider backup/disaster restore remains an operator
qualification for the real realm.

## Maintenance and remaining limits

The read-only upstream/security check reports release **1.23.2**, no newer
release and zero new/updated advisories relative to the reviewed public
snapshots. This is not an exhaustive vulnerability scan. Weekly/on-demand
automation opens reviewable update/security draft PRs, gates pending source
review, explicitly dispatches qualification, and has no deployment step.
Maintenance owner: **@DecisionNerd**. The GitHub workflows have been inspected
locally but have not run in GitHub; no push or PR was created.

Only linux/arm64 and this synthetic local shared-trust corpus are qualified by
the recorded runs. Production ingress, credentials, issuer/client/group,
backup procedures, workers and other architectures still require deployment
acceptance. Audio/video were not exercised; upstream functionality remains but
no secondary-workload acceptance is claimed. The upstream oversized-avatar validator returns HTTP 500 for a page larger
than its 1200-pixel avatar limit; this pre-existing validation behavior is outside
the auth patch. Valid one-pixel avatar upload/delete passes. Full upstream test coverage,
eight-hour endurance and a production identity-provider disaster restore are
not claimed. Retained drafts are in memory and require keeping the editor tab
open; browser crash/navigation recovery is outside this proof.

There is no back-channel logout, project ACL isolation, reviewer separation,
server-enforced blind annotation, new PDF/document UX, downstream canonical
registry, evaluation service or immutable publication. Provider removal/global
logout is bounded by local lease renewal. Separate access cohorts require
isolated instances with data and credential boundaries. Keep labeling closed
if an upgrade, critical security fix or deployment qualification fails; retain
data/mappings and the prior qualified bridge image.
