#!/usr/bin/env python3
"""Generate throwaway test realm/credentials locally. Never modify a real realm."""

import json
import os
import secrets
from pathlib import Path

root = Path(__file__).parent / ".local"
root.mkdir(mode=0o700, exist_ok=True)
# qualify.sh may already have created this directory with the host umask.
root.chmod(0o700)
if (root / "qualification.env").exists():
    raise SystemExit("Already prepared; preserving local identities and secrets")
os.umask(0o077)
password, kc_password, client_secret, admin = [secrets.token_urlsafe(32) for _ in range(4)]
users = []
credentials = {}
for name in ["alice", "bob", "denied"]:
    secret = secrets.token_urlsafe(24)
    credentials[name] = secret
    users.append(
        {
            "username": name,
            "email": name + "@example.test",
            "emailVerified": True,
            "enabled": True,
            "firstName": name.title(),
            "lastName": "Labeler",
            "credentials": [{"type": "password", "value": secret, "temporary": False}],
            "groups": ["/verdant/labeling/shared"] if name != "denied" else [],
        }
    )
realm = {
    "realm": "labeling",
    "enabled": True,
    "registrationAllowed": False,
    "sslRequired": "all",
    "defaultSignatureAlgorithm": "RS256",
    "accessTokenLifespan": 300,
    "groups": [{"name": "verdant", "subGroups": [{"name": "labeling", "subGroups": [{"name": "shared"}]}]}],
    "users": users,
    "clients": [
        {
            "clientId": "label-studio",
            "secret": client_secret,
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "implicitFlowEnabled": False,
            "serviceAccountsEnabled": False,
            "redirectUris": ["https://labels.localhost:8443/oidc/callback/"],
            "webOrigins": [],
            "attributes": {
                "pkce.code.challenge.method": "S256",
                "post.logout.redirect.uris": "https://labels.localhost:8443/oidc/logged-out/",
            },
            "protocolMappers": [
                {
                    "name": "admission",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-group-membership-mapper",
                    "config": {
                        "claim.name": "groups",
                        "full.path": "true",
                        "id.token.claim": "true",
                        "access.token.claim": "false",
                        "userinfo.token.claim": "false",
                    },
                }
            ],
        }
    ],
}
(root / "realm.json").write_text(json.dumps(realm, indent=2) + "\n")
# A file bind mount keeps Linux ownership: Keycloak's UID differs from the
# runner's UID. The private parent protects host credentials; the read-only
# file mount deliberately gives the trusted Keycloak container import access.
(root / "realm.json").chmod(0o644)
(root / "credentials.json").write_text(json.dumps(credentials) + "\n")
(root / "qualification.env").write_text(
    f"POSTGRE_PASSWORD={password}\nLS_OIDC_ISSUER=https://keycloak.localhost:8443/realms/labeling\n"
    f"LS_OIDC_CLIENT_ID=label-studio\nLS_OIDC_CLIENT_SECRET={client_secret}\n"
    "LS_OIDC_GROUP=/verdant/labeling/shared\nLS_OIDC_ORGANIZATION_ID=1\n"
    "LS_OIDC_ORIGIN=https://labels.localhost:8443\nLS_MACHINE_ORIGIN=https://machine.localhost:8443\nLOG_LEVEL=WARNING\n"
)
(root / "database.env").write_text(f"POSTGRES_DB=labeling\nPOSTGRES_USER=labeling\nPOSTGRES_PASSWORD={password}\n")
(root / "keycloak-database.env").write_text(
    f"POSTGRES_DB=keycloak\nPOSTGRES_USER=keycloak\nPOSTGRES_PASSWORD={kc_password}\n"
)
(root / "keycloak.env").write_text(
    f"KC_DB=postgres\nKC_DB_URL=jdbc:postgresql://keycloak-db:5432/keycloak\nKC_DB_USERNAME=keycloak\n"
    f"KC_DB_PASSWORD={kc_password}\nKC_BOOTSTRAP_ADMIN_USERNAME=operator\nKC_BOOTSTRAP_ADMIN_PASSWORD={admin}\n"
)
print("Prepared test-only realm and credentials in ignored .local directory")
