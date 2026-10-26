# Community Keycloak profile

**Candidate, not production qualified.** See [evidence/QUALIFICATION.md](evidence/QUALIFICATION.md).
Maintenance owner: David Spencer, GitHub **@DecisionNerd**, for CurateLabs.
New bridge, tests, fixtures and deployment code use **Apache-2.0**. Upstream
LICENSE and NOTICE remain authoritative; Authlib is BSD-3-Clause and joserfc
is BSD-3-Clause. No paid functionality is required.

This is a thin downstream of upstream Community **1.23.2**, commit
`df96d79183156e556d91825d15fa7721f1145e1a`. The initial worktree was on
development commit `284a2e72f200e89a6269f2bdf047b8f64a3f17ad`; it remains
on its original branch. This candidate branch starts at the reviewed release.
The downstream image rebuilds the upstream frontend with focused native CSRF,
session-expiry and failed-autosave cleanup hooks; no editor redesign. The base labels
itself 1.23.2 and the correct source SHA but its Python distribution reports
1.23.0. Do not infer source revision from that package version.

## Configuration

Select `DJANGO_SETTINGS_MODULE=verdant_ls.settings` and
`PYTHONPATH=/label-studio/label_studio:/label-studio` (already in the image).
All required values below are startup errors when missing. Issuer, browser
origin and machine origin must be HTTPS; each application origin has no path.

| Environment variable | Required/default | Meaning |
| --- | --- | --- |
| `LS_OIDC_ISSUER` | required | Exact canonical organizational realm issuer |
| `LS_OIDC_CLIENT_ID` | required | Dedicated confidential browser client |
| `LS_OIDC_CLIENT_SECRET` | required secret | Backend-only client secret |
| `LS_OIDC_GROUP` | required | Exact signed ID-token admission group |
| `LS_OIDC_ORGANIZATION_ID` | required integer | Explicit existing native organization |
| `LS_OIDC_ORIGIN` | required | Browser origin, e.g. `https://labels.example.org` |
| `LS_MACHINE_ORIGIN` | required, distinct | Private adapter API origin |
| `LS_OIDC_LEASE_SECONDS` | `300`, range 1..300 | Local admission lease, capped by ID-token expiry |
| `LS_OIDC_ABSOLUTE_SECONDS` | `28800`, range lease..28800 | Original absolute deadline, preserved across renewal |
| `DJANGO_DB` | set `postgresql` | Production/qualification DB, not SQLite concurrency |
| `POSTGRE_HOST/PORT/NAME/USER/PASSWORD` | upstream names, port `5432` | Private persistent Label Studio PostgreSQL |
| `SECRET_KEY` | deployment secret, or persisted upstream data-directory key | Persist with DB/media; never rotate casually |
| `REQUESTS_CA_BUNDLE` | system trust by default | Optional complete CA bundle; local profile adds its test CA |

Fixed profile choices: database Django sessions; `__Host-ls_session` cookie,
Secure, HttpOnly, host-only, path `/`, SameSite=Lax. `__Host-ls_csrf` is
Secure/host-only/SameSite=Lax and JS-readable so native same-origin AJAX can
send its CSRF token. No CORS allow-all. Only configured origin hosts are
accepted. A trusted private ingress must overwrite forwarded scheme and
strip identity/proxy authentication headers. Direct app reachability is forbidden.

The authentication transport script also offers an explicit sign-in link in a
new tab on 401, preserving the open editor and its in-memory draft. Return and
retry the action after renewal; no unsafe request is replayed. The native
annotation serializer prevents browser creation/import from claiming another
contributor and preserves original authors during updates. Machine imports
retain upstream explicit attribution semantics; the consumer must distinguish
declared imported authors from the authenticated service import actor.
Access tokens are discarded; refresh tokens are never stored. The logout
ID-token hint is held only in the database session.

`INITIALIZE_SETTINGS_SERVICES=0` is forced by the bridge before importing
upstream settings. The small native opt-out avoids import-time telemetry and
DRF initialization against partially imported settings. Native default behavior
is unchanged outside the bridge profile. Other native changes configure the
native client CSRF/expiry hooks, release failed draft-save state, preserve native
authors and hide the disabled account token form.
The CSRF middleware uses Django's implementation while removing unsafe browser
exemptions, including DRF and upstream csrf_exempt views. Non-cookie machine
requests follow their credential boundary. PostgreSQL is required.
Native slash handling remains in the middleware stack because the stock UI
uses slashless API/telemetry URLs.

## Keycloak contract

Identity operators create one confidential authorization-code client per
instance/environment. Enable client authentication, RS256 and S256 PKCE;
disable implicit, direct-access/password and service-account grants for this
browser client. Allow only exact browser-origin `/oidc/callback/` and
`/oidc/logged-out/` callback/logout URLs. No wildcard web origins. Request
`openid profile email`, never `offline_access`. Release only the necessary
groups in a signed ID-token `groups` mapper, along with verified organizational
email, given/family names. Admission never grants owner/admin/reviewer roles.

The bridge checks exact discovery issuer, HTTPS provider endpoint origin,
RS256 JWKS signature, required issuer/subject/audience/expiry/issued-at/nonce,
authorized party, optional not-before, and exact group/email verification.
Authlib does code exchange, PKCE and token validation; UserInfo is not called.
Metadata and successfully validated JWKS are cached at most 300 seconds per
worker; unknown `kid` invokes Authlib's single forced refresh. Requests time
out after five seconds and errors fail closed. No tokens/claims/codes are logged.

`/oidc/login/?next=/projects/...` is the external entrypoint. Return paths are
relative `/`, `/projects/…`, `/user/account/…`, `/organization/…`, `/people/…`
or `/models/…`, including their slashless roots. Verdant is an external caller,
on a separate origin, with its own cookies and tokens. No Verdant code lives here.

## Local qualification

Requires Docker Compose, Python 3, Node and a Playwright Chromium browser.
Nothing touches a production realm or paid resource. From repository root:

```sh
npm ci --prefix deploy/oidc/browser
deploy/oidc/browser/node_modules/.bin/playwright install chromium
bash deploy/oidc/qualify.sh
```

On macOS an installed Chrome can be used with `LS_BROWSER_CHANNEL=chrome`.
`prepare.py` generates test-only Alice, Bob and denied identities plus random
credentials in ignored, owner-readable `.local/`. It refuses to overwrite them.
Compose pins all base images by digest, persists separate application and
Keycloak PostgreSQL volumes, media/key state, and the local TLS authority.
Only loopback `8443` is published. Browser and containers use exactly
`https://keycloak.localhost:8443/realms/labeling`; issuer rewriting is forbidden.
The application trusts the generated local CA; only the disposable test
browser context tolerates its untrusted local certificate. Do not install this
test CA in organizational trust or expose this profile beyond loopback.

For manual inspection, open `https://labels.localhost:8443/oidc/login/` and use
the generated test credentials. The machine test origin is
`https://machine.localhost:8443`. A separate native service registration is
required; neither browser cookies nor Keycloak access tokens work there.
No service token is supplied in source. Preserve volumes with `compose down`;
do not use `down -v` when retaining identity/annotation evidence.

## Migration and private operators

Readers: Django sessions, native User/OrganizationMember, annotation author FKs,
DRF and native views. Writers: bridge login/provisioning, native profile and
annotation APIs, private operator commands. New tables are additive:
`ExternalIdentity` (unique issuer/subject, one native user, generation),
`ServiceAccount` (explicit unbound native user), `LoginTransaction` (single-use
state/nonce/verifier tied to a DB session). Existing native IDs/FKs never move.

Forward path: close labeling ingress, drain old web/workers, take a coordinated
DB/media/key backup, run migrations once using the candidate image/settings,
explicitly link verified existing contributors, then start the new image on
private ports and qualify it before opening ingress. Do not overlap the public
old password profile with this profile. Additive schema permits a prior
**bridge-qualified** image to read the same mappings; no destructive contraction
is part of this migration. Old signed cookies are ignored by the new cookie
name/backend. Rollback retains mapping tables and native identities.

Commands run through a separately controlled shell/job, never a public fallback:

```sh
python label_studio/manage.py migrate --noinput
# Only an empty deployment: unbound, unusable-password recovery owner.
python label_studio/manage.py bridge_operator bootstrap --email owner@example.org --reason CHANGE-123
# Verify issuer/sub through identity administration, select the native ID.
python label_studio/manage.py bridge_operator link --user-id 42 --issuer https://identity.example.org/realms/organization --subject VERIFIED-SUBJECT --reason CHANGE-124
python label_studio/manage.py bridge_operator revoke --user-id 42 --reason OFFBOARD-125
python label_studio/manage.py bridge_operator enable --user-id 42 --reason ACCESS-126
python label_studio/manage.py bridge_operator create-service --email adapter@example.org --reason SERVICE-127
python label_studio/manage.py bridge_operator register-service --user-id 77 --reason SERVICE-128
python label_studio/manage.py bridge_operator expire-sessions --reason RESTORE-129
python label_studio/manage.py bridge_operator cleanup --reason NIGHTLY-SESSION-CLEANUP
python label_studio/manage.py bridge_inventory
```

Link requires an active ordinary member of the configured organization. No
email-based linking, automatic owner/admin/recovery binding, service binding,
relinking or replacement of removed membership. Same-subject retries retain
the mapping; collisions roll back user/token/membership creation. Names/email
are display data, with verified email renames accepted only when unclaimed.
Bindings and registered users are deletion-protected. Deactivate instead.
Native account first/family-name/phone edits remain available; bridge identity
is independent. Re-enable never restores an old generation's sessions.
Run cleanup daily to prune expired Django sessions and login/logout transactions;
it never removes bindings or contributors.

The service account has an unusable password and a native persistent `Token`
record. Transfer its credential only through the private operator process into
the adapter's secret store. Use `Authorization: Token …` on private machine
`/api/…` routes. The bridge uses native Token authentication with an additional
active/registered/unbound/membership check; local PAT/JWT grants are unnecessary
and their endpoints stay closed. Rotate using the private native `reset_token`
operation and update the adapter secret atomically. Never print it in release
evidence. Existing human token records are retained for native compatibility,
but every browser credential header and machine use of bound-human credentials
is denied. The machine origin/path pair is checked by the application as well
as ingress; credentials cannot establish browser sessions.

## Sessions, expiry and logout

Each protected browser request verifies binding, activity, membership,
generation, lease and absolute deadline locally. Unsafe requests have a DB
transaction and repeat this check at result acceptance, locking the current DB
session row so completed logout/rotation in another tab invalidates the writer.
The request's password hash and generation must still match. A request whose upload
or computation outlives access rolls back its database writes and returns 401.
Native external side effects and orphaned upload files require deployment
qualification; this transaction is not a distributed rollback service.
Safe HTML navigation initiates renewal. API/XHR and unsafe expiry are structured
401 responses with no login HTML and no automatic request replay. Renewal
uses the existing provider session with `prompt=none`, cannot change subject,
and preserves the original eight-hour deadline. Provider errors or missing
admission never extend the prior lease. At the deadline the old session is
cleared and normal code login restarts; Keycloak controls credentials/MFA.

GET `/logout` or `/logout/` displays a confirmation. CSRF-protected POST clears
the DB session. Optional organizational logout captures the server-held hint,
clears local authentication, and uses Authlib RP-initiated logout with a separate
single-use database transaction. `/oidc/logged-out/` does not immediately log in.
Local logout need not terminate another application's Keycloak session.

No back-channel logout is claimed. Provider disable/group removal/realm logout
is observed by the next renewal, at most the configured lease for subsequent
protected requests. Local revoke/enable changes the generation and is checked
on the next protected request without a provider call. Actual measurements,
editor drafts, two tabs and in-flight upload outcomes belong in release evidence.

## Kubernetes, persistence and restore

`kubernetes.yaml` is a production reference for the same image/settings and
migration command. Render an immutable `${CANDIDATE_IMAGE}` and a unique
`${RELEASE_ID}` for its migration Job; replace example
hosts/database/CIDR/controller values. Supply `ls-oidc-secrets` externally with
`SECRET_KEY`, `POSTGRE_PASSWORD`, `LS_OIDC_CLIENT_SECRET`. Run/wait for the release
migration Job before starting/replacing the web Deployment. It uses Recreate
with one persistent media volume; scale/storage changes require qualification.
If workers are enabled, run native `rqworker` using this exact image/settings.
The identity operators own the existing persistent Keycloak realm and client.

Keep database ports private. Permit app-port traffic only from the configured
ingress namespace, and machine ingress only from the adapter network or mTLS
identity. The reference machine ingress rewrites `/api/…` to internal
`/machine/api/…` while preserving the machine Host. Browser ingress must not
rewrite its Host to machine. Strip all untrusted identity headers; replace the
forwarded scheme. CORS is not CSRF protection. Qualify those controller-specific
rules, persistence, issuer DNS/TLS and ingress bypass attempts in the actual cluster.

Back up native user/membership/task/annotation and bridge tables together with
media and persistent secret key. Include Keycloak state in the identity team's
coordinated recovery plan. Stop ingress/writers for a consistent restore.
After restoring run `bridge_operator expire-sessions` **before reopening**:
it deletes DB sessions/login transactions and increments all human generations.
Do not restore valid old login transactions. Verify existing subjects resolve to
the same native IDs and committed annotations/media match their digests.

Rollback means the prior qualified bridge image plus compatible schema and
data, not the upstream password/signed-cookie profile. Keep labeling entry
closed if compatibility, critical security fixes or SSO qualification fail.
Never delete contributor mappings to recover service.

## Maintenance and promotion

`oidc-upstream-review.yml` checks upstream release and Label Studio/Authlib
security notifications weekly and on demand,
stages a merge on an update branch, and opens one draft PR. Conflicts are
recorded in a reviewable candidate file when the merge cannot be staged.
It dispatches candidate qualification because GITHUB_TOKEN-created PR events
do not trigger workflows automatically. It has no deployment step. New or
updated advisories are compared with reviewed evidence snapshots and open a
security-review draft even without a new upstream release. Actions must permit
this workflow to create PRs and dispatch tests. Pending source/image review
blocks qualification. Subscribe the owner to upstream release/security
notifications; prioritize security fixes. This repository's native policies
determine PR targets. No automatic tracking/deployment of upstream HEAD.

For every candidate, review source/image SHA correspondence, published
advisories and actual image packages; update the immutable base digest and
hash-locked Authlib/joserfc overlay. The base pins remaining runtime dependencies;
web/yarn.lock and the pinned Node builder define the stock frontend rebuild. `pip check` is required. Record both source
commit and image manifest/config digest; rebuilding is pinned-input repeatable,
not a claim of bit-for-bit identical image timestamps/provenance.

`oidc-qualification.yml` builds the candidate and runs the native DB/protocol
and real Keycloak/browser checks. Review the full `bridge_inventory` output,
including endpoint-specific authenticators; the runtime rejects newly introduced
authenticator classes until reviewed. Every upgrade repeats legacy URL, CSRF,
human Token/X-Api-Key/PAT/JWT, conflicting-cookie/header, service-browser,
spoofed-header, direct-port and automatic-credential checks. No startup source
rewriting or runtime monkey patch is used. The small browser request hook is
an authentication integration, not an editor replacement.

Run `release_evidence.py` after the build, then record the measured session/
removal bounds, migration/restart/restore outcomes and native author/draft
evidence in a reviewed release record. Publish/promote only the tested immutable
image through the normal deployment path; retain the prior qualified image.
CI green or one successful login does not authorize promotion. A growing patch
set or repeated upstream conflicts triggers a scope review by the owner.

One CE instance is a shared-trust environment. Projects are not access
isolation, and SSO supplies no reviewer separation, blind review or evaluation
authority. Separate cohorts require separate instances and data/credential
boundaries. The consuming platform owns canonical revisions, originals,
adjudication, evaluation and immutable publication. Fixture page digests and
coordinates describe native interchange, not a canonical registry or richer
PDF/document product.

Ingress logging must omit callback query strings, Authorization headers and
request bodies. The reference app ingresses disable access logs. Configure the
NGINX controller with `error-log-level: crit` and a query-free access format such
as `$remote_addr $host $request_method $uri $status $request_time`; the local
kind harness applies these settings. Caddy access logs are off and request-bearing
proxy error logs are excluded. Do not enable browser traces/HAR or provider debug
logging in acceptance runs that can capture codes, tokens or client secrets.
