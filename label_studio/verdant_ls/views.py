import logging
import time

from authlib.integrations.base_client import OAuthError
from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.contrib.auth import logout as django_logout
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods
from users.functions import login as native_login

from .identity import AdmissionDenied, provision
from .protocol import cache_keys, claims_options, client, consume, return_path, save_transaction

audit = logging.getLogger("verdant_ls")


def denied(request, *args, **kwargs):
    return JsonResponse({"detail": "This authentication path is disabled"}, status=403)


@require_GET
def token_settings(request):
    # AccessGate requires a current bound session. Keep native account/profile
    # rendering while advertising no usable human non-session credentials.
    return JsonResponse({"api_tokens_enabled": False, "legacy_api_tokens_enabled": False, "api_token_ttl_days": 0})


@require_GET
def login(request):
    try:
        target = return_path(request.GET.get("next", "/"))
        now = time.time()
        existing = request.session.get("bridge")
        if existing and now >= existing["absolute"]:
            django_logout(request)
            existing = None
        oidc = client()
        response = oidc.authorize_redirect(
            request, settings.OIDC_ORIGIN + "/oidc/callback/", **({"prompt": "none"} if existing else {})
        )
        save_transaction(request, oidc, response, "login", {"next": target, "previous": existing})
        return response
    except AdmissionDenied:
        return JsonResponse({"detail": "Login request rejected"}, status=400)
    except Exception:
        audit.warning("oidc_start_failed")
        return JsonResponse({"detail": "Identity provider unavailable; retry login"}, status=503)


@require_GET
@ensure_csrf_cookie
def callback(request):
    try:
        saved = consume(request, "login")
    except AdmissionDenied:
        # An unsolicited callback must not log out an existing browser session.
        audit.warning("oidc_transaction_denied")
        return render(request, "verdant_ls/denied.html", status=403)
    try:
        oidc = client()
        oidc.framework.set_state_data(request.session, request.GET["state"], saved["authlib"])
        token = oidc.authorize_access_token(request, claims_options=claims_options(), leeway=0)
        cache_keys(oidc)
        claims = token.get("userinfo")
        if not token.get("id_token") or not claims:
            raise AdmissionDenied("id_token")
        # Authlib enforces aud/azp/nonce/time/signature. Also require azp whenever
        # present, even on a single-audience token (OIDC's stricter client rule).
        if claims.get("azp", settings.OIDC_CLIENT_ID) != settings.OIDC_CLIENT_ID:
            raise AdmissionDenied("azp")
        previous = saved["previous"]
        now = time.time()
        if previous and now >= previous["absolute"]:
            raise AdmissionDenied("absolute")
        identity = provision(
            claims, previous["user"] if previous else None, previous["generation"] if previous else None
        )
        absolute = previous["absolute"] if previous else now + settings.OIDC_ABSOLUTE_SECONDS
        # Explicit rotation also covers renewal of the same native user.
        request.session.cycle_key()
        native_login(request, identity.user, backend="verdant_ls.backends.BoundSessionBackend")
        request.session["bridge"] = {
            "user": identity.user_id,
            "generation": identity.session_generation,
            "lease": min(now + settings.OIDC_LEASE_SECONDS, claims["exp"], absolute),
            "absolute": absolute,
        }
        request.session["bridge_id_token"] = token["id_token"]
        request.session["organization_pk"] = settings.OIDC_ORGANIZATION_ID
        request.session.set_expiry(max(1, int(absolute - now)))
        audit.info("oidc_login_accepted user_id=%s", identity.user_id)
        return redirect(saved["next"])
    except AdmissionDenied as error:
        audit.warning("oidc_login_denied reason=%s", str(error))
    except Exception:
        audit.warning("oidc_callback_failed")
    django_logout(request)
    return render(request, "verdant_ls/denied.html", status=403)


@require_http_methods(["GET", "POST"])
@csrf_protect
def logout(request):
    if request.method == "GET":
        return render(request, "verdant_ls/logout.html")
    hint = request.session.get("bridge_id_token")
    organizational = request.POST.get("organizational") == "yes"
    django_logout(request)
    if organizational and hint:
        try:
            oidc = client()
            response = oidc.logout_redirect(request, settings.OIDC_ORIGIN + "/oidc/logged-out/", id_token_hint=hint)
            save_transaction(request, oidc, response, "logout", {})
            return response
        except Exception:
            audit.warning("oidc_logout_provider_failed")
    return render(request, "verdant_ls/logged_out.html")


@require_GET
def logged_out(request):
    try:
        saved = consume(request, "logout")
        # State validation is local; a provider outage must not block completion
        # of an already-returned logout callback.
        oidc = OAuth().register("keycloak", client_id=settings.OIDC_CLIENT_ID)
        oidc.framework.set_state_data(request.session, request.GET["state"], saved["authlib"])
        oidc.validate_logout_response(request)
        return render(request, "verdant_ls/logged_out.html")
    except (AdmissionDenied, OAuthError, KeyError):
        return HttpResponseForbidden("Invalid logout transaction")
