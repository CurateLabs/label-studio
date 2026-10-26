import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from organizations.models import Organization, OrganizationMember
from users.models import User

from .models import ExternalIdentity, ServiceAccount

audit = logging.getLogger("verdant_ls")


class AdmissionDenied(Exception):
    pass


def member(user):
    return (
        OrganizationMember.objects.filter(
            user=user, organization_id=settings.OIDC_ORGANIZATION_ID, deleted_at__isnull=True
        ).exists()
        and user.active_organization_id == settings.OIDC_ORGANIZATION_ID
    )


def allowed(identity):
    user = identity.user
    return (
        identity.issuer == settings.OIDC_ISSUER
        and user.is_active
        and member(user)
        and not ServiceAccount.objects.filter(user=user).exists()
    )


def profile(claims):
    if (
        claims.get("iss") != settings.OIDC_ISSUER
        or not isinstance(claims.get("sub"), str)
        or not 0 < len(claims["sub"]) <= 255
    ):
        raise AdmissionDenied("identity")
    groups = claims.get("groups")
    if not isinstance(groups, list) or settings.OIDC_GROUP not in groups or claims.get("email_verified") is not True:
        raise AdmissionDenied("admission")
    email = claims.get("email")
    try:
        if not isinstance(email, str) or len(email) > User._meta.get_field("email").max_length:
            raise ValidationError("email")
        validate_email(email)
    except ValidationError:
        raise AdmissionDenied("profile") from None
    names = [claims.get("given_name", ""), claims.get("family_name", "")]
    if any(not isinstance(n, str) or len(n) > 256 for n in names):
        raise AdmissionDenied("profile")
    return User.objects.normalize_email(email), names


def provision(claims, expected_user=None, expected_generation=None):
    """All account, token signal, membership and binding writes roll back together.

    Lock the configured organization to serialize first login and email checks.
    No email-based resolution. Existing bindings never recreate memberships.
    """
    email, names = profile(claims)
    try:
        with transaction.atomic():
            org = Organization.objects.select_for_update().get(pk=settings.OIDC_ORGANIZATION_ID)
            identity = (
                ExternalIdentity.objects.select_for_update()
                .filter(issuer=claims["iss"], subject=claims["sub"])
                .first()
            )
            if identity is None:
                if expected_user is not None or User.objects.filter(email__iexact=email).exists():
                    raise AdmissionDenied("collision")
                user = User.objects.create_user(email=email, password=None, username=email.split("@")[0])
                org.add_user(user)
                user.active_organization = org
                user.save(update_fields=["active_organization"])
                identity = ExternalIdentity.objects.create(issuer=claims["iss"], subject=claims["sub"], user=user)
            else:
                user = User.objects.select_for_update().get(pk=identity.user_id)
                identity.user = user
            if expected_user is not None and (
                user.pk != expected_user or identity.session_generation != expected_generation
            ):
                raise AdmissionDenied("renewal_identity")
            if not allowed(identity):
                raise AdmissionDenied("local_access")
            if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
                raise AdmissionDenied("collision")
            user.email, user.first_name, user.last_name = email, *names
            user.save(update_fields=["email", "first_name", "last_name"])
            return identity
    except IntegrityError:
        # Re-read only after the failed transaction/savepoint has rolled back.
        winner = ExternalIdentity.objects.filter(issuer=claims["iss"], subject=claims["sub"]).first()
        if winner and winner.user.email == email and allowed(winner):
            if expected_user is None or (
                winner.user_id == expected_user and winner.session_generation == expected_generation
            ):
                return winner
        raise AdmissionDenied("collision") from None
