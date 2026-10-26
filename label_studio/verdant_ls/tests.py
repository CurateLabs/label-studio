"""Real native models, PostgreSQL transactions and Authlib signature validation."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.core.management import call_command
from django.db import close_old_connections
from django.db.models.deletion import ProtectedError
from django.test import Client, RequestFactory, TransactionTestCase
from django.utils import timezone
from joserfc import jwt
from joserfc.jwk import RSAKey
from organizations.models import Organization, OrganizationMember
from rest_framework.authtoken.models import Token
from users.models import User

from .identity import AdmissionDenied, provision
from .models import ExternalIdentity, LoginTransaction
from .protocol import consume, digest, return_path


class BridgeTests(TransactionTestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="recovery@example.test")
        self.org = Organization.objects.create(
            pk=settings.OIDC_ORGANIZATION_ID, title="Qualification", created_by=self.owner
        )
        self.client = Client(
            enforce_csrf_checks=True, HTTP_HOST=urlsplit(settings.OIDC_ORIGIN).netloc, HTTP_ORIGIN=settings.OIDC_ORIGIN
        )
        self.key = RSAKey.generate_key(2048)
        self.claims = {
            "iss": settings.OIDC_ISSUER,
            "sub": "alice",
            "aud": settings.OIDC_CLIENT_ID,
            "iat": int(time.time()) - 1,
            "exp": int(time.time()) + 240,
            "email": "alice@example.test",
            "email_verified": True,
            "groups": [settings.OIDC_GROUP],
            "given_name": "Alice",
            "family_name": "Labeler",
        }
        self.oidc = OAuth().register(
            "keycloak",
            client_id=settings.OIDC_CLIENT_ID,
            client_secret="test-only",
            authorization_endpoint=settings.OIDC_ISSUER + "/auth",
            token_endpoint=settings.OIDC_ISSUER + "/token",
            issuer=settings.OIDC_ISSUER,
            jwks={"keys": [self.key.as_dict(private=False)]},
            id_token_signing_alg_values_supported=["RS256"],
            client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
        )

    def tearDown(self):
        # Test runner flush uses SQL rather than contributor deletion signals.
        from core.current_request import CurrentContext

        CurrentContext.clear()

    def signed_login(self, claims=None, signing_key=None):
        with patch("verdant_ls.views.client", return_value=self.oidc):
            start = self.client.get("/oidc/login/", secure=True)
            self.assertEqual(start.status_code, 302)
            params = parse_qs(urlsplit(start.url).query)
            self.assertEqual(params["code_challenge_method"], ["S256"])
            data = {**self.claims, "nonce": params["nonce"][0], **(claims or {})}
            encoded = jwt.encode({"alg": "RS256"}, data, signing_key or self.key)
            with patch.object(
                self.oidc, "fetch_access_token", return_value={"id_token": encoded, "access_token": "discarded"}
            ):
                response = self.client.get(
                    "/oidc/callback/", {"state": params["state"][0], "code": "test-only"}, secure=True
                )
            return response, params["state"][0]

    def test_real_authlib_callback_rotation_and_replay(self):
        old = self.client.session.session_key
        response, state = self.signed_login()
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        self.assertNotEqual(old, session.session_key)
        self.assertIn("last_login", session)
        self.assertNotIn("access_token", session)
        self.assertNotIn("refresh_token", session)
        self.assertLessEqual(session["bridge"]["lease"], self.claims["exp"])
        self.assertEqual(self.client.get("/api/current-user/whoami", secure=True).status_code, 200)
        self.assertEqual(
            self.client.get("/oidc/callback/", {"state": state, "code": "test-only"}, secure=True).status_code, 403
        )
        self.assertEqual(User.objects.exclude(pk=self.owner.pk).count(), 1)
        self.assertEqual(self.client.get("/api/current-user/whoami", secure=True).status_code, 200)

    def test_negative_protocol(self):
        cases = [
            {"iss": "https://wrong.example/realm"},
            {"aud": "wrong-client"},
            {"azp": "wrong-client"},
            {"aud": [settings.OIDC_CLIENT_ID, "other"]},
            {"exp": int(time.time()) - 20},
            {"iat": int(time.time()) + 120},
            {"nbf": int(time.time()) + 120},
            {"nonce": None},
            {"nonce": "wrong", "nonce_supported": False},
            {"sub": ""},
        ]
        for case in cases:
            with self.subTest(fields=list(case)):
                self.assertEqual(self.signed_login(case)[0].status_code, 403)
                self.assertEqual(User.objects.exclude(pk=self.owner.pk).count(), 0)

    def test_unsigned_and_unknown_key(self):
        self.assertEqual(self.signed_login(signing_key=RSAKey.generate_key(2048))[0].status_code, 403)
        with self.assertRaises(Exception):
            self.oidc.parse_id_token({"id_token": "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ4In0."}, nonce="x")

    def test_admission_rolls_back(self):
        for changes in [{"groups": []}, {"email_verified": False}, {"email": "invalid"}]:
            with self.assertRaises(AdmissionDenied):
                provision({**self.claims, **changes})
        self.assertEqual(User.objects.exclude(pk=self.owner.pk).count(), 0)
        self.assertEqual(Token.objects.exclude(user=self.owner).count(), 0)
        self.assertEqual(OrganizationMember.objects.count(), 0)

    def test_profiles_collision_and_recycled_email(self):
        identity = provision(self.claims)
        renamed = provision({**self.claims, "email": "renamed@example.test"})
        self.assertEqual(renamed.user_id, identity.user_id)
        User.objects.create_user(email="taken@example.test")
        with self.assertRaises(AdmissionDenied):
            provision({**self.claims, "email": "taken@example.test"})
        with self.assertRaises(AdmissionDenied):
            provision({**self.claims, "sub": "recycled", "email": "renamed@example.test"})
        identity.user.refresh_from_db()
        self.assertEqual(identity.user.email, "renamed@example.test")

    def test_existing_email_never_links(self):
        existing = User.objects.create_user(email=self.claims["email"])
        self.org.add_user(existing)
        existing.active_organization = self.org
        existing.save()
        with self.assertRaises(AdmissionDenied):
            provision(self.claims)
        self.assertFalse(ExternalIdentity.objects.exists())
        call_command(
            "bridge_operator",
            "link",
            user_id=existing.pk,
            subject="alice",
            issuer=settings.OIDC_ISSUER,
            reason="test-verification",
        )
        self.assertEqual(provision(self.claims).user_id, existing.pk)

    def test_removed_member_disabled_user_and_protection(self):
        identity = provision(self.claims)
        with self.assertRaises(ProtectedError):
            identity.delete()
        with self.assertRaises(ProtectedError):
            identity.user.delete()
        OrganizationMember.objects.filter(user=identity.user).update(deleted_at=timezone.now())
        with self.assertRaises(AdmissionDenied):
            provision(self.claims)
        self.assertEqual(OrganizationMember.objects.count(), 1)

    def test_revoke_enable_generation_and_lease(self):
        self.assertEqual(self.signed_login()[0].status_code, 302)
        identity = ExternalIdentity.objects.get()
        call_command("bridge_operator", "revoke", user_id=identity.user_id, reason="test")
        call_command("bridge_operator", "enable", user_id=identity.user_id, reason="test")
        self.assertEqual(self.client.get("/api/current-user/whoami", secure=True).status_code, 401)
        self.assertEqual(self.signed_login()[0].status_code, 302)
        session = self.client.session
        session["bridge"] = {**session["bridge"], "lease": time.time() - 1}
        session.save()
        self.assertEqual(self.client.post("/api/projects/", {}, secure=True).status_code, 401)
        self.assertEqual(self.client.get("/", HTTP_ACCEPT="text/html", secure=True).status_code, 302)

    def test_renewal_cannot_switch_subject_or_extend_absolute(self):
        self.assertEqual(self.signed_login()[0].status_code, 302)
        absolute = self.client.session["bridge"]["absolute"]
        self.assertEqual(self.signed_login()[0].status_code, 302)
        self.assertEqual(self.client.session["bridge"]["absolute"], absolute)
        self.assertEqual(self.signed_login({"sub": "bob", "email": "bob@example.test"})[0].status_code, 403)
        self.assertEqual(ExternalIdentity.objects.count(), 1)

    def test_credentials_and_legacy_routes(self):
        self.assertEqual(self.signed_login()[0].status_code, 302)
        token = Token.objects.get(user=ExternalIdentity.objects.get().user)
        for header in [
            {"HTTP_AUTHORIZATION": "Token " + token.key},
            {"HTTP_X_API_KEY": token.key},
            {"HTTP_AUTHORIZATION": "Bearer a.b.c"},
        ]:
            self.assertEqual(self.client.get("/api/projects/", secure=True, **header).status_code, 401)
        for path in [
            "/user/signup/",
            "/user/signup/?token=invite",
            "/admin/login/",
            "/api-auth/login/",
            "/api/current-user/token",
            "/api/current-user/reset-token/",
            "/api/token/",
            "/api/token/refresh/",
            "/api/token/rotate/",
            "/api/token/blacklist/",
            "/api/jwt/settings",
        ]:
            for method in ["get", "post"]:
                self.assertEqual(getattr(self.client, method)(path, secure=True).status_code, 403, path)
        self.assertEqual(self.client.post("/user/login/", secure=True).status_code, 403)

    def test_csrf_and_logout(self):
        self.assertEqual(self.signed_login()[0].status_code, 302)
        self.assertEqual(self.client.post("/api/projects/", {"title": "No CSRF"}, secure=True).status_code, 403)
        csrf = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        response = self.client.post("/api/projects/", {"title": "CSRF checked"}, secure=True, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.client.get("/logout", secure=True).status_code, 200)
        self.assertEqual(self.client.get("/api/current-user/whoami", secure=True).status_code, 200)
        self.assertEqual(self.client.post("/logout", secure=True).status_code, 403)
        self.assertEqual(self.client.post("/logout", secure=True, HTTP_X_CSRFTOKEN=csrf).status_code, 200)
        self.assertEqual(self.client.get("/api/current-user/whoami", secure=True).status_code, 401)

    def test_service_only_machine_api(self):
        user = User.objects.create_user(email="service@example.test")
        self.org.add_user(user)
        user.active_organization = self.org
        user.save()
        call_command("bridge_operator", "register-service", user_id=user.pk, reason="test")
        token = Token.objects.get(user=user).key
        machine = Client(HTTP_HOST=urlsplit(settings.OIDC_MACHINE_ORIGIN).netloc)
        header = {"HTTP_AUTHORIZATION": "Token " + token}
        self.assertEqual(machine.get("/machine/api/projects/", secure=True, **header).status_code, 200)
        self.assertEqual(machine.get("/api/projects/", secure=True, **header).status_code, 403)
        self.assertEqual(machine.get("/machine/", secure=True, **header).status_code, 403)
        with self.assertRaises(Exception):
            call_command(
                "bridge_operator",
                "link",
                user_id=user.pk,
                subject="service",
                issuer=settings.OIDC_ISSUER,
                reason="test",
            )
        self.assertEqual(machine.get("/machine/api/projects/", secure=True).status_code, 401)

    def test_concurrent_first_login(self):
        def worker():
            close_old_connections()
            try:
                return provision(self.claims).user_id
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(User.objects.exclude(pk=self.owner.pk).count(), 1)
        self.assertEqual(Token.objects.exclude(user=self.owner).count(), 1)
        self.assertEqual(OrganizationMember.objects.count(), 1)

    def test_atomic_callback_consumption(self):
        session = SessionStore()
        session.create()
        LoginTransaction.objects.create(
            state_digest=digest("state"),
            session_digest=digest(session.session_key),
            purpose="login",
            payload={"authlib": {}},
            expires_at=timezone.now() + timedelta(minutes=1),
        )

        def worker():
            close_old_connections()
            request = RequestFactory().get("/oidc/callback/?state=state")
            request.session = SessionStore(session_key=session.session_key)
            try:
                consume(request, "login")
                return True
            except AdmissionDenied:
                return False
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: worker(), range(2))), [False, True])

    def test_return_url_allowlist(self):
        for value in [
            "https://evil.test/",
            "//evil.test/",
            "/\\evil.test",
            "/admin/",
            "/oidc/login/",
            "/machine/api/projects/",
        ]:
            with self.assertRaises(AdmissionDenied):
                return_path(value)
        self.assertEqual(return_path("/projects/1/data?tab=1"), "/projects/1/data?tab=1")
        self.assertEqual(return_path("/projects"), "/projects")
        self.assertEqual(return_path("/people/"), "/people/")

    def test_result_acceptance_rolls_back_expired_mutation(self):
        from django.http import JsonResponse
        from projects.models import Project

        from .middleware import AccessGate

        identity = provision(self.claims)
        request = RequestFactory().post("/api/projects/", HTTP_HOST=urlsplit(settings.OIDC_ORIGIN).netloc)
        request.user = identity.user
        request.session = SessionStore()
        request.session["bridge"] = {
            "user": identity.user_id,
            "generation": 0,
            "lease": time.time() + 60,
            "absolute": time.time() + 600,
        }
        request.session["_auth_user_id"] = str(identity.user_id)
        request.session["_auth_user_hash"] = identity.user.get_session_auth_hash()
        request.session.save()

        def slow_view(request):
            Project.objects.create(title="Must roll back", organization=self.org, created_by=identity.user)
            request.session["bridge"]["lease"] = time.time() - 1
            return JsonResponse({"created": True}, status=201)

        self.assertEqual(AccessGate(slow_view)(request).status_code, 401)
        self.assertFalse(Project.objects.filter(title="Must roll back").exists())

    def test_logout_in_another_tab_rolls_back_inflight_mutation(self):
        from django.contrib.sessions.models import Session
        from django.http import JsonResponse
        from projects.models import Project

        from .middleware import AccessGate

        identity = provision(self.claims)
        request = RequestFactory().post("/api/projects/", HTTP_HOST=urlsplit(settings.OIDC_ORIGIN).netloc)
        request.user = identity.user
        request.session = SessionStore()
        request.session["bridge"] = {
            "user": identity.user_id,
            "generation": 0,
            "lease": time.time() + 60,
            "absolute": time.time() + 600,
        }
        request.session["_auth_user_id"] = str(identity.user_id)
        request.session["_auth_user_hash"] = identity.user.get_session_auth_hash()
        request.session.save()

        def concurrent_logout():
            close_old_connections()
            try:
                Session.objects.filter(session_key=request.session.session_key).delete()
            finally:
                close_old_connections()

        def inflight_view(request):
            Project.objects.create(
                title="Logged out before acceptance", organization=self.org, created_by=identity.user
            )
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(concurrent_logout).result()
            return JsonResponse({"created": True}, status=201)

        self.assertEqual(AccessGate(inflight_view)(request).status_code, 401)
        self.assertFalse(Project.objects.filter(title="Logged out before acceptance").exists())

    def test_jwks_unknown_key_refreshes_once(self):
        rotated = RSAKey.generate_key(2048, parameters={"kid": "new-key"})
        claims = {**self.claims, "nonce": "transaction-nonce"}
        encoded = jwt.encode({"alg": "RS256", "kid": "new-key"}, claims, rotated)
        with patch.object(
            self.oidc,
            "fetch_jwk_set",
            side_effect=[{"keys": [self.key.as_dict(private=False)]}, {"keys": [rotated.as_dict(private=False)]}],
        ) as fetch:
            result = self.oidc.parse_id_token({"id_token": encoded}, nonce="transaction-nonce", leeway=0)
            self.assertEqual(result["sub"], "alice")
            self.assertEqual(fetch.call_count, 2)

    def test_group_removed_on_renewal_and_provider_outage(self):
        self.assertEqual(self.signed_login()[0].status_code, 302)
        session = self.client.session
        session["bridge"] = {**session["bridge"], "lease": time.time() - 1}
        session.save()
        with patch("verdant_ls.views.client", side_effect=OSError("provider unavailable")):
            self.assertEqual(self.client.get("/oidc/login/", secure=True).status_code, 503)
        self.assertEqual(self.client.get("/api/current-user/whoami", secure=True).status_code, 401)
        self.assertEqual(self.signed_login({"groups": []})[0].status_code, 403)
        self.assertEqual(ExternalIdentity.objects.count(), 1)

    def test_browser_author_cannot_be_spoofed(self):
        from projects.models import Project
        from tasks.models import Task

        self.assertEqual(self.signed_login()[0].status_code, 302)
        user = ExternalIdentity.objects.get().user
        project = Project.objects.create(title="Provenance", organization=self.org, created_by=user)
        task = Task.objects.create(project=project, data={"text": "Synthetic"})
        csrf = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        response = self.client.post(
            f"/api/tasks/{task.pk}/annotations/",
            {"result": [], "completed_by": self.owner.pk},
            content_type="application/json",
            secure=True,
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(task.annotations.count(), 0)

    def test_unsigned_token_with_otherwise_valid_claims(self):
        import base64
        import json

        claims = {**self.claims, "nonce": "expected-nonce"}

        def encode(value):
            return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

        unsigned = encode({"alg": "none"}) + "." + encode(claims) + "."
        with self.assertRaises(Exception):
            self.oidc.parse_id_token({"id_token": unsigned}, nonce="expected-nonce", leeway=0)

    def test_discovery_issuer_and_provider_timeouts(self):
        from django.core.cache import cache

        from .protocol import client

        cache.clear()
        metadata = {
            "issuer": settings.OIDC_ISSUER,
            **{
                name: settings.OIDC_ISSUER + "/" + name
                for name in ["authorization_endpoint", "token_endpoint", "jwks_uri", "end_session_endpoint"]
            },
        }
        with patch("verdant_ls.protocol.requests.get") as get:
            get.return_value.json.return_value = metadata
            oidc = client()
            self.assertEqual(get.call_args.kwargs["timeout"], 5)
            with oidc._get_session() as session:
                self.assertEqual(session.default_timeout, 5)
            with oidc._get_oauth_client() as session:
                self.assertEqual(session.default_timeout, 5)
        cache.clear()
        with patch("verdant_ls.protocol.requests.get") as get:
            get.return_value.json.return_value = {**metadata, "issuer": "https://wrong.example/realm"}
            with self.assertRaises(AdmissionDenied):
                client()

    def test_native_csrf_exemption_cannot_bypass_browser_policy(self):
        self.assertEqual(self.signed_login()[0].status_code, 302)
        self.assertEqual(self.client.post("/__lsa/", {}, secure=True).status_code, 403)
        self.assertEqual(self.client.get("/trigger500/", secure=True).status_code, 403)

    def test_additive_migration_preserves_existing_native_authorship(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        from projects.models import Project
        from tasks.models import Annotation, Task

        existing = User.objects.create_user(email="existing@example.test", password="test-only")
        self.org.add_user(existing)
        existing.active_organization = self.org
        existing.save()
        project = Project.objects.create(title="Existing corpus", organization=self.org, created_by=existing)
        task = Task.objects.create(project=project, data={"text": "Existing committed work"})
        annotation = Annotation.objects.create(task=task, completed_by=existing, result=[])
        token_pk = Token.objects.get(user=existing).pk
        try:
            MigrationExecutor(connection).migrate([("verdant_ls", None)])
            MigrationExecutor(connection).migrate([("verdant_ls", "0001_initial")])
            self.assertEqual(ExternalIdentity.objects.count(), 0)
            call_command(
                "bridge_operator",
                "link",
                user_id=existing.pk,
                issuer=settings.OIDC_ISSUER,
                subject="existing-subject",
                reason="migration-proof",
            )
            annotation.refresh_from_db()
            self.assertEqual(annotation.completed_by_id, existing.pk)
            self.assertEqual(Token.objects.get(user=existing).pk, token_pk)
            self.assertEqual(ExternalIdentity.objects.get().user_id, existing.pk)
        finally:
            MigrationExecutor(connection).migrate([("verdant_ls", "0001_initial")])

    def test_stale_tab_401_cannot_clear_a_rotated_session_cookie(self):
        from django.http import JsonResponse

        from .middleware import BridgeSessionMiddleware

        request = RequestFactory().get("/api/projects/")
        request.COOKIES[settings.SESSION_COOKIE_NAME] = "stale-session"
        request.session = SessionStore()
        middleware = BridgeSessionMiddleware(lambda request: JsonResponse({}, status=401))
        response = middleware.process_response(request, JsonResponse({}, status=401))
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        request.path = "/logout"
        response = middleware.process_response(request, JsonResponse({}))
        self.assertEqual(response.cookies[settings.SESSION_COOKIE_NAME]["max-age"], 0)
