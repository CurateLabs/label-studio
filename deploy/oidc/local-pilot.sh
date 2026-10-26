#!/usr/bin/env bash
# Apache-2.0. Qualify, publish locally, then consume exactly that manifest.
set -euo pipefail
cd "$(dirname "$0")/../.."
local_dir=deploy/oidc/.local
mkdir -p "$local_dir"
chmod 700 "$local_dir"
umask 077
unset LS_QUALIFICATION_ROLLBACK_IMAGE COMPOSE_PROJECT_NAME
export LS_OIDC_IMAGE=label-studio-oidc:candidate
export LS_QUALIFICATION_RUNTIME=compose
rm -f "$local_dir/pilot-ready.json"
revision=$(git rev-parse HEAD)
# Image labels must identify committed build inputs, including untracked files.
image_paths=(label_studio web deploy/oidc/Dockerfile deploy/oidc/requirements.lock deploy/oidc/uwsgi.ini pyproject.toml poetry.lock .dockerignore LICENSE NOTICE)
if [ -n "$(git status --porcelain -- "${image_paths[@]}")" ]; then
  printf '%s\n' 'Commit image inputs before qualifying a source-labelled pilot image.' >&2
  exit 1
fi

# A failed run must never leave a previous ready receipt looking current.
bash deploy/oidc/qualify.sh
python3 deploy/oidc/release_evidence.py > "$local_dir/pilot-build.json"
if [ "$(git rev-parse HEAD)" != "$revision" ] || [ -n "$(git status --porcelain -- "${image_paths[@]}")" ]; then
  printf '%s\n' 'Image inputs changed during qualification; refusing publication.' >&2
  exit 1
fi
image_revision=$(docker image inspect label-studio-oidc:candidate --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
test "$image_revision" = "$revision"
candidate_id=$(docker image inspect label-studio-oidc:candidate --format '{{.Id}}')

docker compose -f deploy/oidc/local-registry.yml up -d
registry_ready=0
for attempt in {1..30}; do
  if curl --fail --silent http://localhost:5001/v2/ > /dev/null; then registry_ready=1; break; fi
  sleep 1
done
test "$registry_ready" = 1
repository=localhost:5001/label-studio-oidc
docker tag "$candidate_id" "$repository:$revision"
docker push "$repository:$revision"
# Resolve and verify the server's manifest, not Docker's configuration ID.
manifest_headers=$(curl --fail --silent --head -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json' "http://localhost:5001/v2/label-studio-oidc/manifests/$revision")
manifest_digest=$(printf '%s\n' "$manifest_headers" | tr -d '\r' | awk 'tolower($1) == "docker-content-digest:" { print $2 }')
if ! [[ "$manifest_digest" =~ ^sha256:[a-f0-9]{64}$ ]]; then
  printf '%s\n' 'Registry did not return a valid immutable manifest digest.' >&2
  exit 1
fi
export LS_OIDC_IMAGE="$repository@$manifest_digest"
docker pull "$LS_OIDC_IMAGE"
pulled_id=$(docker image inspect "$LS_OIDC_IMAGE" --format '{{.Id}}')
test "$pulled_id" = "$candidate_id"
printf 'LS_OIDC_IMAGE=%s\n' "$LS_OIDC_IMAGE" > "$local_dir/pilot-image.env"
docker compose -f deploy/oidc/compose.yml up -d web
application_ready=0
for attempt in {1..60}; do
  if curl --fail --silent --cacert "$local_dir/root.crt" --resolve labels.localhost:8443:127.0.0.1 https://labels.localhost:8443/logout/ > /dev/null; then application_ready=1; break; fi
  sleep 1
done
test "$application_ready" = 1
# Re-run native browser/authorship checks and persistence against the pulled
# manifest. These remain fork interoperability evidence, not Verdant acceptance.
node deploy/oidc/browser/qualify.cjs
node deploy/oidc/browser/restart.cjs
python3 deploy/oidc/restore_proof.py
python3 - "$revision" "$candidate_id" "$manifest_digest" <<'PY'
import datetime
import json
import os
import sys
from pathlib import Path

revision, image_id, manifest_digest = sys.argv[1:]
local = Path('deploy/oidc/.local')
record = {
    'scope': 'local fork interoperability pilot; Verdant integration remains blocked on its platform prerequisites',
    'qualified_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'fork_sha': revision,
    'image': os.environ['LS_OIDC_IMAGE'],
    'image_manifest_digest': manifest_digest,
    'docker_image_id': image_id,
    'browser_origin': 'https://labels.localhost:8443',
    'machine_origin': 'https://machine.localhost:8443',
    'issuer': 'https://keycloak.localhost:8443/realms/labeling',
    'production_qualified': False,
}
(local / 'pilot-ready.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
PY
