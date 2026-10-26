from django.contrib.auth.backends import BaseBackend

from .identity import allowed
from .models import ExternalIdentity


class BoundSessionBackend(BaseBackend):
    def get_user(self, user_id):
        identity = ExternalIdentity.objects.select_related("user").filter(user_id=user_id).first()
        return identity.user if identity and allowed(identity) else None
