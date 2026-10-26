import json

from django.core.management.base import BaseCommand
from django.urls import URLPattern, URLResolver, get_resolver


class Command(BaseCommand):
    help = "Emit the resolved URL/authenticator inventory for release review; no credentials."

    def handle(self, **options):
        rows = []

        def walk(patterns, prefix=""):
            for entry in patterns:
                route = prefix + str(entry.pattern)
                if isinstance(entry, URLResolver):
                    walk(entry.url_patterns, route)
                elif isinstance(entry, URLPattern):
                    callback = entry.callback
                    cls = getattr(callback, "cls", None)
                    rows.append(
                        {
                            "route": route,
                            "view": f"{callback.__module__}.{callback.__name__}",
                            "authenticators": [
                                f"{auth.__module__}.{auth.__name__}" for auth in cls.authentication_classes
                            ]
                            if cls
                            else [],
                            "csrf_exempt": bool(getattr(callback, "csrf_exempt", False)),
                        }
                    )

        walk(get_resolver().url_patterns)
        self.stdout.write(json.dumps(rows, indent=2))
