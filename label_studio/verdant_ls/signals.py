from django.db.models.deletion import ProtectedError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import ExternalIdentity, ServiceAccount


@receiver(pre_delete, sender=ExternalIdentity)
@receiver(pre_delete, sender=ServiceAccount)
def preserve_contributors(sender, instance, **kwargs):
    raise ProtectedError("Retain contributor bindings; deactivate or revoke instead.", [instance])
