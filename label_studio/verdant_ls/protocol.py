import hashlib
from datetime import timedelta
from urllib.parse import urlsplit

import requests
from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .identity import AdmissionDenied
from .models import LoginTransaction


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def client():
    """Fresh Authlib client with bounded shared metadata/JWKS cache and TLS I/O.

    Metadata is fetched from exactly one configured issuer. Authlib performs code
    exchange, PKCE and JWT verification; no handwritten OAuth/JWT implementation.
    """
    key = "bridge-discovery-" + digest(settings.OIDC_ISSUER)
    metadata = cache.get(key)
    if metadata is None:
        response = requests.get(settings.OIDC_ISSUER + "/.well-known/openid-configuration", timeout=5)
        response.raise_for_status()
        metadata = response.json()
        if metadata.get("issuer") != settings.OIDC_ISSUER:
            raise AdmissionDenied("issuer")
        origin = urlsplit(settings.OIDC_ISSUER)
        for name in ["authorization_endpoint", "token_endpoint", "jwks_uri", "end_session_endpoint"]:
            endpoint = urlsplit(metadata.get(name, ""))
            if (
                endpoint.scheme != "https"
                or endpoint.netloc != origin.netloc
                or endpoint.username
                or endpoint.fragment
            ):
                raise AdmissionDenied("metadata")
        metadata["id_token_signing_alg_values_supported"] = ["RS256"]
        cache.set(key, metadata, 300)
    oauth = OAuth()
    oidc = oauth.register(
        "keycloak",
        client_id=settings.OIDC_CLIENT_ID,
        client_secret=settings.OIDC_CLIENT_SECRET,
        client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256", "default_timeout": 5},
        **metadata,
    )
    jwks = cache.get("bridge-jwks-" + digest(settings.OIDC_ISSUER))
    if jwks:
        oidc.server_metadata["jwks"] = jwks
    return oidc


def cache_keys(oidc):
    keys = oidc.server_metadata.get("jwks")
    if keys:
        cache.set("bridge-jwks-" + digest(settings.OIDC_ISSUER), keys, 300)


def save_transaction(request, oidc, response, purpose, extra):
    from urllib.parse import parse_qs

    state = parse_qs(urlsplit(response.url).query)["state"][0]
    payload = oidc.framework.get_state_data(request.session, state)
    oidc.framework.clear_state_data(request.session, state)
    if not request.session.session_key:
        request.session.create()
    LoginTransaction.objects.update_or_create(
        session_digest=digest(request.session.session_key),
        purpose=purpose,
        defaults={
            "state_digest": digest(state),
            "payload": {"authlib": payload, **extra},
            "expires_at": timezone.now() + timedelta(minutes=5),
            "consumed": False,
        },
    )


def consume(request, purpose):
    state = request.GET.get("state", "")
    key = request.session.session_key
    if not key or not state or len(state) > 256:
        raise AdmissionDenied("transaction")
    query = LoginTransaction.objects.filter(
        state_digest=digest(state),
        session_digest=digest(key),
        purpose=purpose,
        expires_at__gt=timezone.now(),
        consumed=False,
    )
    # Atomic conditional UPDATE: concurrent callbacks cannot both win, including
    # different workers. Autocommit releases the row lock before provider I/O.
    if query.update(consumed=True) != 1:
        raise AdmissionDenied("transaction")
    record = LoginTransaction.objects.get(state_digest=digest(state))
    payload = record.payload
    record.payload = {}  # Erase nonce/verifier promptly, retain consumed marker.
    record.save(update_fields=["payload"])
    return payload


def claims_options():
    return {
        "iss": {"essential": True, "value": settings.OIDC_ISSUER},
        "sub": {"essential": True},
        "aud": {"essential": True},
        "exp": {"essential": True},
        "iat": {"essential": True},
        "nonce": {"essential": True},
    }


def return_path(value):
    if not value:
        return "/"
    parts = urlsplit(value)
    if (
        parts.scheme
        or parts.netloc
        or "\\" in value
        or any(ord(c) < 32 for c in value)
        or not value.startswith("/")
        or value.startswith("//")
        or not (
            parts.path == "/"
            or any(
                parts.path == p.rstrip("/") or parts.path.startswith(p)
                for p in settings.OIDC_RETURN_PREFIXES
                if p != "/"
            )
        )
    ):
        raise AdmissionDenied("return_path")
    return value
