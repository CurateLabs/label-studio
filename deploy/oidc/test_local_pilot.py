"""Image selection and failed-qualification publication boundaries. Apache-2.0."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class LocalPilotTests(unittest.TestCase):
    def layout(self, directory, script):
        root = Path(directory)
        deploy = root / "deploy/oidc"
        local = deploy / ".local"
        local.mkdir(parents=True)
        shutil.copyfile(Path(__file__).with_name(script), deploy / script)
        commands = root / "commands"
        commands.mkdir()
        env = {**os.environ, "PATH": str(commands) + os.pathsep + os.environ["PATH"]}
        return root, deploy, local, commands, env

    def command(self, directory, name, body):
        path = directory / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o700)

    def test_qualification_overrides_inherited_image_before_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root, deploy, local, commands, env = self.layout(directory, "qualify.sh")
            (local / "qualification.env").touch()
            (local / "realm.json").write_text("{}")
            (root / ".env").write_text("LS_OIDC_IMAGE=unqualified:from-dotenv\n")
            self.command(commands, "git", "printf '%040d\\n' 1\n")
            self.command(commands, "docker", 'printf "%s" "$LS_OIDC_IMAGE" > deploy/oidc/.local/selected\nexit 71\n')
            result = subprocess.run(
                ["bash", str(deploy / "qualify.sh")],
                cwd=root, env={**env, "LS_OIDC_IMAGE": "unqualified:inherited"}, capture_output=True,
            )
            self.assertEqual(result.returncode, 71)
            self.assertEqual((local / "selected").read_text(), "label-studio-oidc:candidate")

    def test_failed_qualification_clears_receipt_and_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            root, deploy, local, commands, env = self.layout(directory, "local-pilot.sh")
            (local / "pilot-ready.json").write_text("{}")
            self.command(commands, "git", 'if [ "$1" = rev-parse ]; then printf "%040d\\n" 1; fi\n')
            self.command(commands, "docker", 'touch deploy/oidc/.local/docker-called\nexit 99\n')
            (deploy / "qualify.sh").write_text(
                "python3 - <<'PY'\nimport json,os\nfrom pathlib import Path\n"
                "Path('deploy/oidc/.local/selected').write_text(json.dumps({k:os.environ.get(k) for k in "
                "['LS_OIDC_IMAGE','LS_QUALIFICATION_RUNTIME','LS_QUALIFICATION_ROLLBACK_IMAGE','COMPOSE_PROJECT_NAME']}))\n"
                "PY\nexit 72\n"
            )
            result = subprocess.run(
                ["bash", str(deploy / "local-pilot.sh")], cwd=root, capture_output=True,
                env={**env, "LS_OIDC_IMAGE": "unqualified:inherited", "LS_QUALIFICATION_RUNTIME": "kubernetes",
                     "LS_QUALIFICATION_ROLLBACK_IMAGE": "old:cluster", "COMPOSE_PROJECT_NAME": "another-stack"},
            )
            self.assertEqual(result.returncode, 72)
            self.assertFalse((local / "pilot-ready.json").exists())
            self.assertFalse((local / "docker-called").exists())
            self.assertEqual(json.loads((local / "selected").read_text()), {
                "LS_OIDC_IMAGE": "label-studio-oidc:candidate", "LS_QUALIFICATION_RUNTIME": "compose",
                "LS_QUALIFICATION_ROLLBACK_IMAGE": None, "COMPOSE_PROJECT_NAME": None,
            })
