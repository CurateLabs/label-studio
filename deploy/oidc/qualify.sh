#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
compose=(docker compose -f deploy/oidc/compose.yml)
local_dir=deploy/oidc/.local
mkdir -p "$local_dir"
python3 - <<'PY'
import json,pathlib
candidate=pathlib.Path('deploy/oidc/upstream-candidate.json')
if candidate.exists() and json.loads(candidate.read_text())['status'].startswith('UNQUALIFIED'):
    raise SystemExit('Upstream source/image/seam review is pending; retain the deployed image')
PY
if [ ! -f "$local_dir/qualification.env" ]; then python3 deploy/oidc/prepare.py; fi
docker build -f deploy/oidc/Dockerfile --metadata-file "$local_dir/build-metadata.json" --build-arg "FORK_REVISION=$(git rev-parse HEAD)" -t label-studio-oidc:candidate .
python3 - <<'PY'
import json,pathlib,subprocess
candidate=pathlib.Path('deploy/oidc/upstream-candidate.json')
if candidate.exists():
    image=json.loads(subprocess.check_output(['docker','image','inspect','label-studio-oidc:candidate']))[0]
    assert image['Config']['Labels']['org.labelstudio.upstream.revision']==json.loads(candidate.read_text())['sha'], 'Reviewed source and image pins differ'
PY
"${compose[@]}" up -d database keycloak-db keycloak ingress
for attempt in {1..30}; do
  if "${compose[@]}" cp ingress:/data/caddy/pki/authorities/local/root.crt "$local_dir/root.crt" 2>/dev/null; then break; fi
  sleep 1
done
# Public CA bundle only; no TLS verification bypass in the application.
docker run --rm --entrypoint cat label-studio-oidc:candidate /etc/ssl/cert.pem > "$local_dir/trust.pem"
cat "$local_dir/root.crt" >> "$local_dir/trust.pem"
chmod 644 "$local_dir/trust.pem"
"${compose[@]}" up -d web
for attempt in {1..30}; do
  if "${compose[@]}" exec -T web python -c 'import os,requests; requests.get(os.environ["LS_OIDC_ISSUER"]+"/.well-known/openid-configuration",timeout=3).raise_for_status()' >/dev/null 2>&1; then break; fi
  sleep 1
done
# Explicitly TEST-ONLY empty-install bootstrap; never run this script on a real realm/database.
"${compose[@]}" exec -T web python /label-studio/label_studio/manage.py shell -c \
  'from django.core.management import call_command; from organizations.models import Organization; call_command("bridge_operator", "bootstrap", email="recovery@example.test", reason="local-qualification") if not Organization.objects.exists() else None'
"${compose[@]}" exec -T web python /label-studio/label_studio/manage.py test verdant_ls.tests --noinput
npm ci --prefix deploy/oidc/browser --ignore-scripts --no-audit --no-fund
node --test deploy/oidc/browser/auth-hooks.test.cjs
node deploy/oidc/browser/qualify.cjs
node deploy/oidc/browser/lifecycle.cjs
node deploy/oidc/browser/outage.cjs
node deploy/oidc/browser/provider-removal.cjs
python3 deploy/oidc/restore_proof.py
"${compose[@]}" exec -T web python /label-studio/label_studio/manage.py bridge_inventory > deploy/oidc/evidence/routes.json
