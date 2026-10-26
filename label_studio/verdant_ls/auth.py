from rest_framework.authentication import BaseAuthentication, SessionAuthentication, TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


def service_credentials(request):
    from .identity import member
    from .models import ExternalIdentity, ServiceAccount

    result = TokenAuthentication().authenticate(request)
    if not result:
        raise AuthenticationFailed("Registered service credential required")
    user, token = result
    if (
        not user.is_active
        or not member(user)
        or not ServiceAccount.objects.filter(user=user).exists()
        or ExternalIdentity.objects.filter(user=user).exists()
    ):
        raise AuthenticationFailed("Registered service credential required")
    return user, token


class NativeAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return "Session"

    def authenticate(self, request):
        if getattr(request._request, "bridge_machine", False):
            return service_credentials(request)
        if request.META.get("HTTP_AUTHORIZATION") or request.META.get("HTTP_X_API_KEY"):
            raise AuthenticationFailed("Browser credentials must use a bound session")
        return SessionAuthentication().authenticate(request)
