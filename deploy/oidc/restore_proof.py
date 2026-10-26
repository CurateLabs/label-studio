#!/usr/bin/env python3
"""Test-only coordinated snapshot/restore into a new private database and volume.

Run while qualification annotation/media writers are quiescent. Never overwrites
or drops the source database, source volume or an existing restore target.
"""

import json
import os
import subprocess
import time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
local = root / "deploy/oidc/.local"
compose = ["docker", "compose", "-f", str(root / "deploy/oidc/compose.yml")]
image = os.environ.get("LS_OIDC_IMAGE", "label-studio-oidc:candidate")
suffix = str(int(time.time()))
database = "labeling_restore_" + suffix
volume = "ls-oidc-qualification-restore-" + suffix
snapshot_code = """
import hashlib,json
from pathlib import Path
from django.conf import settings
from django.contrib.sessions.models import Session
from verdant_ls.models import ExternalIdentity,LoginTransaction
from tasks.models import Annotation,Task
from organizations.models import OrganizationMember
media={str(p.relative_to(settings.BASE_DATA_DIR)):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(settings.BASE_DATA_DIR).rglob('*') if p.is_file() and p.name!='.env'}
print(json.dumps({'bindings':list(ExternalIdentity.objects.order_by('pk').values('issuer','subject','user_id','session_generation')),
'annotations':list(Annotation.objects.order_by('pk').values('id','task_id','completed_by_id','updated_by_id','result')),
'tasks':list(Task.objects.order_by('pk').values('id','project_id','data')),
'memberships':list(OrganizationMember.objects.order_by('pk').values('id','user_id','organization_id','deleted_at')),
'sessions':Session.objects.count(),'transactions':LoginTransaction.objects.count(),'media':media,'secret_key':settings.SECRET_KEY},default=str,sort_keys=True))
"""


def run(*args, data=None):
    return subprocess.run(args, input=data, check=True, capture_output=True, cwd=root).stdout


def snapshot(prefix):
    data = run(*prefix, "python", "/label-studio/label_studio/manage.py", "shell", "-c", snapshot_code)
    return json.loads(data.decode().strip().splitlines()[-1])


os.umask(0o077)
before = snapshot([*compose, "exec", "-T", "web"])
dump = run(*compose, "exec", "-T", "database", "pg_dump", "-U", "labeling", "-d", "labeling", "-Fc")
archive = run(*compose, "exec", "-T", "web", "tar", "-cf", "-", "-C", "/label-studio/data", ".")
(local / "labeling.dump").write_bytes(dump)
(local / "media.tar").write_bytes(archive)
run(*compose, "exec", "-T", "database", "createdb", "-U", "labeling", database)
run(*compose, "exec", "-T", "database", "pg_restore", "-U", "labeling", "-d", database, "--no-owner", data=dump)
run("docker", "volume", "create", volume)
run(
    "docker",
    "run",
    "--rm",
    "-i",
    "-u",
    "0",
    "-v",
    volume + ":/restore",
    "--entrypoint",
    "tar",
    image,
    "-xf",
    "-",
    "-C",
    "/restore",
    data=archive,
)
restored = [
    "docker",
    "run",
    "--rm",
    "--network",
    "ls-oidc-qualification_private",
    "--env-file",
    str(local / "qualification.env"),
    "-e",
    "DJANGO_DB=postgresql",
    "-e",
    "POSTGRE_HOST=database",
    "-e",
    "POSTGRE_USER=labeling",
    "-e",
    "POSTGRE_NAME=" + database,
    "-v",
    volume + ":/label-studio/data",
    image,
]
run(
    *restored,
    "python",
    "/label-studio/label_studio/manage.py",
    "bridge_operator",
    "expire-sessions",
    "--reason",
    "isolated-restore-qualification",
)
after = snapshot(restored)
for field in ["annotations", "tasks", "memberships", "media", "secret_key"]:
    assert before[field] == after[field], "Restore mismatch: " + field
expected = [{**binding, "session_generation": binding["session_generation"] + 1} for binding in before["bindings"]]
assert expected == after["bindings"], "Native bindings changed beyond generation rotation"
assert after["sessions"] == 0 and after["transactions"] == 0
evidence = {
    "passed": True,
    "docker_image_id": json.loads(run("docker", "image", "inspect", image))[0]["Id"],
    "restore_database": database,
    "restore_volume": volume,
    "source_retained": True,
    "native_user_ids": [b["user_id"] for b in after["bindings"]],
    "annotations_preserved": len(after["annotations"]),
    "tasks_preserved": len(after["tasks"]),
    "media_files_preserved": len(after["media"]),
    "secret_key_preserved": True,
    "generation_incremented": True,
    "restored_sessions": 0,
    "restored_transactions": 0,
}
(root / "deploy/oidc/evidence/restore.json").write_text(json.dumps(evidence, indent=2) + "\n")
print(json.dumps(evidence))
