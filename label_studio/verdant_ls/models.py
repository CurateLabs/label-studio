from django.conf import settings
from django.db import models


class ExternalIdentity(models.Model):
    issuer = models.CharField(max_length=512)
    subject = models.CharField(max_length=255)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="external_identity")
    session_generation = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["issuer", "subject"], name="bridge_issuer_subject")]


class ServiceAccount(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registered_at = models.DateTimeField(auto_now_add=True)


class LoginTransaction(models.Model):
    """One pending transaction per session/purpose. Consumed with an atomic UPDATE.

    Authlib state includes nonce and verifier; it never leaves the server database.
    An UPDATE takes the database row lock, with no lock held across provider I/O.
    """

    state_digest = models.CharField(max_length=64, unique=True)
    session_digest = models.CharField(max_length=64)
    purpose = models.CharField(max_length=8)
    payload = models.JSONField()
    expires_at = models.DateTimeField()
    consumed = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session_digest", "purpose"], name="bridge_pending_session")]
