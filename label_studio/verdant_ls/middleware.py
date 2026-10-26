import logging
import time
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import logout
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import transaction
from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.shortcuts import redirect
from django.utils.cache import patch_vary_headers
from rest_framework.exceptions import AuthenticationFailed

from .auth import service_credentials
from .identity import allowed
from .models import ExternalIdentity

audit = logging.getLogger("verdant_ls")
PUBLIC_BROWSER_PATHS = frozenset(
    ["/oidc/login/", "/oidc/callback/", "/oidc/logged-out/", "/logout", "/logout/", "/user/login", "/user/login/"]
)


class BridgeSessionMiddleware(SessionMiddleware):
    def process_response(self, request, response):
        if request.path not in PUBLIC_BROWSER_PATHS and response.status_code == 401:
            # A stale tab's failed request must not erase the cookie installed
            # by another tab's successful session rotation. The gate invalidates
            # server-side state; explicit login/logout keeps normal cookie rules.
            patch_vary_headers(response, ("Cookie",))
            return response
        return super().process_response(request, response)


class BrowserCSRF(CsrfViewMiddleware):
    """The browser profile has no unsafe CSRF exemptions, including native APIs.

    Machine requests have already passed non-cookie credential admission. The
    standard Django CSRF implementation owns all browser token/origin checks.
    """

    def process_view(self, request, callback, args, kwargs):
        if getattr(request, "bridge_machine", False):
            return None
        return super().process_view(request, self.protected_view, args, kwargs)

    @staticmethod
    def protected_view(request):
        pass

    def _reject(self, request, reason):
        if request.path.startswith("/api/"):
            return JsonResponse({"detail": "CSRF verification failed"}, status=403)
        return super()._reject(request, reason)


def blocked(path):
    return path.startswith(
        (
            "/user/signup",
            "/admin",
            "/api-auth",
            "/api/token",
            "/api/jwt/",
            "/django-rq",
            "/api/current-user/reset-token",
            "/api/current-user/token",
        )
    )


class AccessGate:
    def __init__(self, get_response):
        self.get_response = get_response

    def process_view(self, request, view, args, kwargs):
        # Fail closed when an upgrade introduces a new endpoint authenticator.
        cls = getattr(view, "cls", None)
        if cls:
            from .auth import NativeAuthentication

            if not cls.authentication_classes or any(
                auth is not NativeAuthentication for auth in cls.authentication_classes
            ):
                return JsonResponse({"detail": "Unqualified authentication boundary"}, status=403)

    @staticmethod
    def current_browser_access(request):
        from django.contrib.auth import HASH_SESSION_KEY, SESSION_KEY
        from django.contrib.sessions.models import Session
        from django.utils import timezone
        from django.utils.crypto import constant_time_compare

        data = request.session.get("bridge", {})
        # Serialize result acceptance with DB-session deletion/rotation. A second
        # tab's completed logout or renewal must invalidate an in-flight writer.
        session = (
            Session.objects.select_for_update()
            .filter(session_key=request.session.session_key, expire_date__gt=timezone.now())
            .first()
        )
        if session is None:
            return False
        stored = session.get_decoded()
        stored_bridge = stored.get("bridge", {})
        identity = ExternalIdentity.objects.select_related("user").filter(user_id=data.get("user")).first()
        now = time.time()
        return (
            request.user.is_authenticated
            and identity
            and request.user.pk == identity.user_id
            and allowed(identity)
            and data.get("generation") == identity.session_generation
            and stored_bridge.get("user") == identity.user_id
            and stored_bridge.get("generation") == identity.session_generation
            and stored.get(SESSION_KEY) == str(identity.user_id)
            and any(
                constant_time_compare(stored.get(HASH_SESSION_KEY, ""), value)
                for value in [identity.user.get_session_auth_hash(), *identity.user.get_session_auth_fallback_hash()]
            )
            and now < min(data.get("lease", 0), stored_bridge.get("lease", 0))
            and now < min(data.get("absolute", 0), stored_bridge.get("absolute", 0))
        )

    def __call__(self, request):
        request.embed_project_id = None
        machine_host = request.get_host() == urlsplit(settings.OIDC_MACHINE_ORIGIN).netloc
        machine_path = request.path.startswith("/machine/")
        if machine_host != machine_path:
            return JsonResponse({"detail": "Ingress boundary rejected"}, status=403)
        request.bridge_machine = machine_host and machine_path
        request.editor_keymap = settings.EDITOR_KEYMAP
        if request.bridge_machine:
            path = request.path[len("/machine") :]
            if not path.startswith("/api/") or blocked(path) or request.COOKIES.get(settings.SESSION_COOKIE_NAME):
                return JsonResponse({"detail": "Machine API only"}, status=403)
            try:
                request.user, request.auth = service_credentials(request)
            except AuthenticationFailed:
                return JsonResponse({"detail": "Registered service credential required"}, status=401)
        else:
            # Reject before *any* endpoint-specific authenticator; DRF repeats
            # this boundary. A header cannot replace a browser session identity.
            if request.META.get("HTTP_AUTHORIZATION") or request.META.get("HTTP_X_API_KEY"):
                return JsonResponse({"detail": "Browser session required"}, status=401)
            if blocked(request.path) or (request.path.startswith("/user/login") and request.method != "GET"):
                return JsonResponse({"detail": "Authentication path disabled"}, status=403)
            public = request.path in PUBLIC_BROWSER_PATHS
            assets = request.path.startswith(
                ("/static/", "/react-app/", "/label-studio-frontend/", "/dm/")
            ) and request.method in ["GET", "HEAD"]
            if not public and not assets:
                data = request.session.get("bridge", {})
                identity = ExternalIdentity.objects.select_related("user").filter(user_id=data.get("user")).first()
                now = time.time()
                valid = (
                    request.user.is_authenticated
                    and identity
                    and request.user.pk == identity.user_id
                    and allowed(identity)
                    and data.get("generation") == identity.session_generation
                )
                expired = now >= data.get("lease", 0) or now >= data.get("absolute", 0)
                if not valid or expired:
                    if data.get("user") is not None:
                        audit.info(
                            "browser_access_denied user_id=%s reason=%s",
                            data["user"],
                            "lease" if valid else "local_access",
                        )
                    if not valid or now >= data.get("absolute", 0):
                        logout(request)
                    interactive = (
                        request.method in ["GET", "HEAD"]
                        and "text/html" in request.headers.get("Accept", "")
                        and not request.path.startswith("/api/")
                    )
                    if interactive:
                        return redirect("/oidc/login/?" + urlencode({"next": request.get_full_path()}))
                    return JsonResponse(
                        {"detail": "Authentication lease expired", "login_url": "/oidc/login/", "retry": False},
                        status=401,
                    )
        public = request.path in PUBLIC_BROWSER_PATHS
        if request.method not in ["GET", "HEAD", "OPTIONS"] and not public:
            # A slow request may outlive its lease while parsing an upload or
            # computing a result. Commit database mutations only if access is
            # still current at result acceptance. No unsafe request is replayed.
            with transaction.atomic():
                response = self.get_response(request)
                if response.status_code >= 400:
                    transaction.set_rollback(True)
                    request.session.modified = False
                    return response
                try:
                    current = (
                        bool(service_credentials(request))
                        if request.bridge_machine
                        else self.current_browser_access(request)
                    )
                except AuthenticationFailed:
                    current = False
                if not current:
                    transaction.set_rollback(True)
                    # Do not save a stale session or overwrite a newer tab's
                    # rotated cookie after a completed logout/renewal.
                    request.session.modified = False
                    return JsonResponse(
                        {
                            "detail": "Access expired before result acceptance",
                            "retry": False,
                            "login_url": "/oidc/login/",
                        },
                        status=401,
                    )
                return response
        return self.get_response(request)
