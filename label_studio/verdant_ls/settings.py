"""Fail-closed browser and machine profile; no upstream bootstrap entrypoint."""

import os
from pathlib import Path
from urllib.parse import urlsplit

# Avoid initializing DRF with partially imported upstream defaults. The native
# opt-out hook also keeps telemetry disabled before any configuration is read.
os.environ["INITIALIZE_SETTINGS_SERVICES"] = "0"
from core.settings.label_studio import *  # noqa: F403,F401
from django.core.exceptions import ImproperlyConfigured


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} is required")
    return value


OIDC_ISSUER = required("LS_OIDC_ISSUER").rstrip("/")
OIDC_CLIENT_ID = required("LS_OIDC_CLIENT_ID")
OIDC_CLIENT_SECRET = required("LS_OIDC_CLIENT_SECRET")
OIDC_GROUP = required("LS_OIDC_GROUP")
OIDC_ORGANIZATION_ID = int(required("LS_OIDC_ORGANIZATION_ID"))
OIDC_ORIGIN = required("LS_OIDC_ORIGIN").rstrip("/")
OIDC_MACHINE_ORIGIN = required("LS_MACHINE_ORIGIN").rstrip("/")
if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":  # noqa: F405
    raise ImproperlyConfigured("The qualified bridge profile requires PostgreSQL")
for value in [OIDC_ISSUER, OIDC_ORIGIN, OIDC_MACHINE_ORIGIN]:
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.query or parts.fragment:
        raise ImproperlyConfigured("Canonical issuer and application origin must be HTTPS URLs")
if urlsplit(OIDC_ORIGIN).path:
    raise ImproperlyConfigured("Application requires its own origin, without a path prefix")
if urlsplit(OIDC_MACHINE_ORIGIN).path or OIDC_MACHINE_ORIGIN == OIDC_ORIGIN:
    raise ImproperlyConfigured("Machine ingress requires a distinct origin without a path prefix")
OIDC_LEASE_SECONDS = int(os.environ.get("LS_OIDC_LEASE_SECONDS", "300"))
OIDC_ABSOLUTE_SECONDS = int(os.environ.get("LS_OIDC_ABSOLUTE_SECONDS", "28800"))
if not 1 <= OIDC_LEASE_SECONDS <= 300 or not OIDC_LEASE_SECONDS <= OIDC_ABSOLUTE_SECONDS <= 28800:
    raise ImproperlyConfigured("Lease must be 1..300 seconds; absolute lifetime lease..28800 seconds")
OIDC_RETURN_PREFIXES = ("/", "/projects/", "/user/account/", "/organization/", "/people/", "/models/")
ROOT_URLCONF = "verdant_ls.urls"
INSTALLED_APPS = [*INSTALLED_APPS, "verdant_ls.apps.BridgeConfig"]  # noqa: F405
AUTHENTICATION_BACKENDS = ["rules.permissions.ObjectPermissionBackend", "verdant_ls.backends.BoundSessionBackend"]
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "__Host-ls_session"
SESSION_COOKIE_DOMAIN = None
SESSION_COOKIE_PATH = "/"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = OIDC_ABSOLUTE_SECONDS
CSRF_COOKIE_NAME = "__Host-ls_csrf"
CSRF_COOKIE_DOMAIN = None
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False  # Stock same-origin AJAX reads this noncredential token.
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = [OIDC_ORIGIN]
USE_ENFORCE_CSRF_CHECKS = True
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = []
CORS_ALLOWED_ORIGIN_REGEXES = []
ALLOWED_HOSTS = [urlsplit(OIDC_ORIGIN).hostname, urlsplit(OIDC_MACHINE_ORIGIN).hostname]
# Ingress overwrites X-Forwarded-Proto; direct app port MUST be private.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = False
LOGIN_URL = "/oidc/login/"
LOGIN_REDIRECT_URL = "/"
DISABLE_SIGNUP_WITHOUT_LINK = True
ALLOW_ORGANIZATION_CREATION = False
BRIDGE_AUTH_ONLY = True
LATEST_VERSION_CHECK = False
SENTRY_DSN = FRONTEND_SENTRY_DSN = ""
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "verdant_ls.middleware.AccessGate",
    "verdant_ls.middleware.BrowserCSRF",
    "django.contrib.messages.middleware.MessageMiddleware",
    "core.middleware.CommonMiddlewareAppendSlashWithoutRedirect",
    "django.middleware.locale.LocaleMiddleware",
    "django_user_agents.middleware.UserAgentMiddleware",
    "core.current_request.ThreadLocalMiddleware",
    "core.middleware.UpdateLastActivityMiddleware",
]
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_AUTHENTICATION_CLASSES": ["verdant_ls.auth.NativeAuthentication"]}  # noqa: F405
TEMPLATES[0]["DIRS"].insert(0, str(Path(__file__).parent / "templates"))  # noqa: F405
# Never log callback URLs, request bodies, provider exceptions or token payloads.
LOGGING["loggers"]["verdant_ls"] = {"handlers": ["console"], "level": "INFO", "propagate": False}  # noqa: F405
for name in ["authlib", "urllib3", "requests", "django.server", "django.request"]:
    LOGGING["loggers"][name] = {"handlers": ["console"], "level": "CRITICAL", "propagate": False}  # noqa: F405
