# Local Verdant handoff

The fork can qualify and publish an image to a loopback-only OSS Distribution
registry. This is a local fork interoperability pilot, not proof that Verdant is
integrated. It uses only generated test identities and synthetic pages. No
production realm, public registry or paid resource is changed.

## Fork image and local runtime

Commit image inputs first, install the browser prerequisites from README.md,
then run:

```sh
LS_BROWSER_CHANNEL=chrome bash deploy/oidc/local-pilot.sh
# Omit LS_BROWSER_CHANNEL on hosts with the pinned Playwright Chromium installed.
```

The script runs the complete existing qualification before publishing. Any
failure stops delivery. It publishes the native-platform image to
`localhost:5001/label-studio-oidc`, resolves the registry manifest digest, pulls
by that digest, verifies the pulled image identity, and recreates the app using
that immutable reference. Native browser/authorship, restart and isolated
DB/media/key restore checks run again against the pulled image. A successful
run writes ignored, owner-readable `.local/pilot-ready.json` and
`.local/pilot-image.env`. The JSON records source and manifest identity; a
Docker configuration ID alone is not a deployable manifest pin.

Restart this exact image without rebuilding:

```sh
env -u LS_OIDC_IMAGE docker compose --env-file deploy/oidc/.local/pilot-image.env -f deploy/oidc/compose.yml up -d web
```

The existing test URLs remain `https://labels.localhost:8443`,
`https://machine.localhost:8443` and the canonical issuer
`https://keycloak.localhost:8443/realms/labeling`. Keep separate browser/machine
origins, exact callbacks, group `/verdant/labeling/shared`, organization 1, and
existing persistent database/media/Keycloak/TLS volumes. Secrets remain in
`.local`; do not copy them into release records. Compose does not synchronize
realm imports after the database is initialized.

The local registry's Apache-2.0 Distribution image is pinned by OCI digest in
`local-registry.yml`; it binds only `127.0.0.1:5001` and stores image blobs in
its named volume. It deliberately has no shared/public authentication scheme.
Do not expose it to a network. A container on another host cannot consume this
localhost reference; public/organizational registry delivery is a separate
release action. Stop it with `docker compose -f deploy/oidc/local-registry.yml
down` without `-v` to preserve images. Retain the previous immutable image and
compatible bridge schema for rollback; never restore public password login.

## Verified Verdant prerequisites and repair sequence

Inspection on 2026-10-26 found Verdant main `23d0036` still implements the
legacy Node/Next.js/Turso digestion application. Its accepted Python/React
platform is a target, not a working backend. There is no native principal store,
backend-owned Keycloak session, Label Studio adapter or revision-bound result
import. The separate #10 foundation worktree contains uncommitted work; do not
take it over or create a competing foundation.

Use existing contracts and issues, rather than a new integration service:

1. Coordinate completion of [Verdant #10](https://github.com/DecisionNerd/verdant/issues/10)
   and [#11](https://github.com/DecisionNerd/verdant/issues/11). Establish the
   actual shared Python services, PostgreSQL principal store and backend-owned
   authorization-code login using a supported OIDC library. Persist principal
   identity by issuer/subject, never email. Keep the fork's identity bridge here.
2. Implement the needed [#12 Compose](https://github.com/DecisionNerd/verdant/issues/12)
   subset using the same test realm with a separate Verdant client and origin.
   Runtime changes to an initialized test realm need supported, idempotent admin
   operations; importing a changed JSON file is not synchronization. Preserve
   subjects. Do not reuse the legacy serviceAuth shared-login helper.
3. Complete the bounded revision/effect prerequisites in
   [#14](https://github.com/DecisionNerd/verdant/issues/14) and
   [#19](https://github.com/DecisionNerd/verdant/issues/19), then implement
   [#23](https://github.com/DecisionNerd/verdant/issues/23) in Verdant's
   Annotation Management boundary. Persist instance/project/task/schema/sample
   revision mappings, verified issuer/subject-to-native-user provenance and
   durable import receipts. Reconcile uncertain native task imports before retry;
   do not blindly duplicate a non-idempotent POST.
4. Consume the pilot's exact manifest and use an explicitly registered native
   service account on the private machine route. Keep its token in Verdant's
   secret store. Handoff links use the allowlisted Label Studio origin and a
   relative `/oidc/login/?next=...` target. Never forward Verdant cookies or bearer
   tokens. Canonical data, revisions and publication remain in Verdant.

This sequence refines Verdant's existing FR-03/05/10/16, architecture and testing
contracts; it does not add a second registry or a replacement frontend. Correct
the stale Enterprise-SAML prerequisite in Verdant's generated-doc source
`apps/docs/src/content/docs/getting-started.md` when its integration is landed.

## Actual integration acceptance

Evidence regimes are protocol/data contracts (A) and real browser journeys (B).
Fork qualification is prerequisite evidence, not completion of these scenarios:

- Given Alice or Bob signed into Verdant through its own Keycloak client, open
  the stock labeling UI from a synthetic dataset/revision assignment without a
  second password; each annotation retains the correct distinct native author.
- Import through Verdant's dedicated service credential; export and ingest through
  its adapter. Verify schema/revision/page/region identity, Unicode/order and
  original author/update actor separately from the authenticated import actor.
- Denied group creates no native account; spoofed/conflicting credentials and
  browser/service cross-use receive explicit 401/403. No token appears in browser
  storage, handoff URLs, source, logs or evidence.
- Duplicate/stale callbacks and uncertain imports produce one durable accepted
  effect or a clear conflict, never silent attribution/revision changes.
- Restart and coordinated restore preserve Verdant's mappings alongside native
  IDs, tasks, annotations and media. Clear restored sessions/transactions and
  verify subsequent real login. Record exact commits, manifest, packages, native
  author evidence, measured removal bound and restore result.

Only after these pass may the Verdant pilot be called integrated. Production
network/storage/worker qualification, provider disaster restore, audio/video and
8-hour endurance remain separate gates. CE instances remain shared-trust cohorts;
projects do not provide isolation or blind annotation.
