# Isolated Kubernetes qualification

This is a local test deployment, using the same image, database, identity realm,
cookie origins and additive migrations as Compose. It never selects the default
kubectl context. Production ingress/secrets and infrastructure remain operator owned.

1. Complete the Compose qualification and its quiescent backup/restore proof.
2. Install OSS kind **v0.33.0**. The Darwin arm64 binary SHA-256 and all dependency
   source/image pins are in `kind-pins.json`; use the official release checksum
   for another architecture. Keep the binary in ignored `.local/kind` or PATH.
3. Create the isolated cluster with `kind.yaml` and
   `--name ls-oidc-qualification --kubeconfig deploy/oidc/.local/kubeconfig`.
   It disables kindnet because network-policy enforcement is required.
4. Connect its node to Docker network `ls-oidc-qualification_private`. Install
   Calico from the exact source in `kind-pins.json`, replacing its three image
   tags with the recorded digests and setting `CALICO_IPV4POOL_CIDR` to
   `10.244.0.0/16`. Install the pinned NGINX kind ingress manifest. Do not use
   floating deployment manifests or images. Wait for CNI and ingress readiness.
5. Import the candidate's exact local platform into containerd, then run
   `python3 deploy/oidc/kind_deploy.py`. It verifies the context name, copies
   test-only secrets privately, configures canonical issuer DNS and CA trust,
   seeds an empty PVC from the quiescent media backup, runs the release migration
   Job, and starts the app. Existing populated media is not overwritten.

Docker's containerd image store can retain a multiarch index while only one
platform is downloaded. If kind's `--all-platforms` import fails with a missing
digest, use the native platform archive, preserving a real repository tag:

```sh
docker image save --platform linux/arm64 label-studio-oidc:candidate > deploy/oidc/.local/candidate-image.tar
docker exec -i ls-oidc-qualification-control-plane ctr --namespace k8s.io images import --platform linux/arm64 --digests - < deploy/oidc/.local/candidate-image.tar
```

Use the equivalent architecture on other hosts. For a digest-only third-party
image, first add its real release tag to the verified digest before archiving.
The resolved platform manifest must match the locked multiarch index. Never
invent a digest alias for different image content.

For HTTPS testing, keep Caddy as the local TLS edge and Keycloak canonical URL.
Adapt a copy of the Caddyfile so browser and machine upstreams point to the kind
node's private Docker IP on port 80. Remove Caddy's machine `/machine` rewrite;
the Kubernetes machine ingress performs that rewrite. Load the copy with
`caddy reload --config /dev/stdin --adapter caddyfile`; do not edit the source
Compose Caddyfile. Only this trusted edge supplies forwarded HTTPS. The test
cluster permits loopback/private test source ranges; production requires the
actual adapter network or mTLS identity.

Run the same `browser/qualify.cjs` and `browser/lifecycle.cjs` with
`LS_QUALIFICATION_RUNTIME=kubernetes`. Confirm the migration Job succeeded,
the selected image matches the candidate, and an unrelated namespace cannot
connect to app port 8080 while the allowed ingress namespace can. Restart the
app pod and compare native bindings, annotations and media digests; retain a
browser context and confirm its DB session and native ID survive the restart.

Before returning routing to Compose, stop test writers and copy the current
Kubernetes PVC media back into the retained Compose media volume. Both app
deployments share the qualification database; losing the newer media would make
that a destructive rollback. Reload the original Caddyfile only after this copy.
Retain the database, PVC and prior image for review. Deleting a test cluster or
volumes is an explicit cleanup action, never a recovery mechanism.
