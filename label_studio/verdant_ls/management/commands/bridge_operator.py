import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from organizations.models import Organization
from users.models import User
from verdant_ls.identity import member
from verdant_ls.models import ExternalIdentity, LoginTransaction, ServiceAccount

audit = logging.getLogger("verdant_ls")


class Command(BaseCommand):
    help = "Private operator process: bootstrap, link, revoke, enable, register-service, expire-sessions."

    def execute(self, *args, **options):
        try:
            return super().execute(*args, **options)
        except CommandError:
            audit.warning(
                "operator_action_denied action=%s user_id=%s reference=%s",
                options.get("action"),
                options.get("user_id"),
                options.get("reason"),
            )
            raise

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=[
                "bootstrap",
                "link",
                "revoke",
                "enable",
                "create-service",
                "register-service",
                "expire-sessions",
                "cleanup",
            ],
        )
        parser.add_argument("--user-id", type=int)
        parser.add_argument("--subject")
        parser.add_argument("--issuer")
        parser.add_argument("--email")
        parser.add_argument(
            "--reason", required=True, help="Audit/change reference; never include credentials or claims"
        )

    @transaction.atomic
    def handle(self, action, **options):
        if not options["reason"].strip():
            raise CommandError("An audit/change reference is required")
        if action == "bootstrap":
            if Organization.objects.exists() or not options["email"]:
                raise CommandError(
                    "Bootstrap requires an empty installation and --email for an unbound recovery owner"
                )
            owner = User.objects.create_user(email=options["email"], password=None, username="Recovery owner")
            org = Organization.objects.create(
                pk=settings.OIDC_ORGANIZATION_ID, title="Shared labeling", created_by=owner
            )
            org.add_user(owner)
            owner.active_organization = org
            owner.save(update_fields=["active_organization"])
        elif action == "create-service":
            if not options["email"] or User.objects.filter(email__iexact=options["email"]).exists():
                raise CommandError("Select an unused service --email; existing accounts use register-service")
            org = Organization.objects.select_for_update().get(pk=settings.OIDC_ORGANIZATION_ID)
            user = User.objects.create_user(email=options["email"], password=None, username="Service adapter")
            org.add_user(user)
            user.active_organization = org
            user.save(update_fields=["active_organization"])
            ServiceAccount.objects.create(user=user)
            options["user_id"] = user.pk
            self.stdout.write(f"Service native user ID: {user.pk}")
        elif action == "expire-sessions":
            from django.contrib.sessions.models import Session

            Session.objects.all().delete()
            LoginTransaction.objects.all().delete()
            ExternalIdentity.objects.update(session_generation=F("session_generation") + 1)
        elif action == "cleanup":
            from django.core.management import call_command
            from django.utils import timezone

            call_command("clearsessions")
            LoginTransaction.objects.filter(expires_at__lte=timezone.now()).delete()
        else:
            org = Organization.objects.select_for_update().get(pk=settings.OIDC_ORGANIZATION_ID)
            try:
                user = User.objects.select_for_update().get(pk=options["user_id"])
            except User.DoesNotExist:
                raise CommandError("Select an existing --user-id") from None
            identity = ExternalIdentity.objects.select_for_update().filter(user=user).first()
            if action in ["link", "register-service"]:
                if (
                    user.is_staff
                    or user.is_superuser
                    or Organization.objects.filter(created_by=user).exists()
                    or not user.is_active
                    or not member(user)
                ):
                    raise CommandError(
                        "Select an active ordinary member; owner/admin/recovery accounts cannot be bound"
                    )
                if identity:
                    if (
                        action != "link"
                        or identity.issuer != options["issuer"]
                        or identity.subject != options["subject"]
                    ):
                        raise CommandError("Account already bound")
                elif action == "link":
                    if (
                        options["issuer"] != settings.OIDC_ISSUER
                        or not options["subject"]
                        or len(options["subject"]) > 255
                        or ServiceAccount.objects.filter(user=user).exists()
                    ):
                        raise CommandError(
                            "Verified canonical issuer/subject required; service accounts cannot be bound"
                        )
                    if ExternalIdentity.objects.filter(issuer=options["issuer"], subject=options["subject"]).exists():
                        raise CommandError("Subject already bound")
                    ExternalIdentity.objects.create(issuer=options["issuer"], subject=options["subject"], user=user)
                else:
                    ServiceAccount.objects.get_or_create(user=user)
                if user.has_usable_password():
                    user.set_unusable_password()
                    user.save(update_fields=["password"])
            else:
                if not identity:
                    raise CommandError("Select a bound human user")
                # Enabling also rotates the generation. No old session can revive.
                identity.session_generation += 1
                identity.save(update_fields=["session_generation"])
                user.is_active = action == "enable"
                user.save(update_fields=["is_active"])
        audit.info("operator_action action=%s user_id=%s reference=%s", action, options["user_id"], options["reason"])
        self.stdout.write(self.style.SUCCESS("Completed; contributor IDs and bindings retained."))
