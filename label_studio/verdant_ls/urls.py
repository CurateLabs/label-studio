from django.urls import include, path, re_path

from . import views

urlpatterns = [
    path("oidc/login/", views.login, name="oidc-login"),
    path("oidc/callback/", views.callback, name="oidc-callback"),
    path("oidc/logged-out/", views.logged_out, name="oidc-logged-out"),
    re_path(r"^user/login/?$", views.login),
    re_path(r"^logout/?$", views.logout, name="bridge-logout"),
    re_path(r"^api/jwt/settings/?$", views.token_settings),
    path("machine/", include(("core.urls", "machine"), namespace="machine")),
    path("", include("core.urls")),
]
