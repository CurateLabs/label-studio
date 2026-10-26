"""Qualification secrets stay private while the non-root provider can import."""

import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PreparationTests(unittest.TestCase):
    def test_existing_directory_becomes_private_and_realm_mount_is_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(Path(__file__).with_name("prepare.py"), root / "prepare.py")
            local = root / ".local"
            local.mkdir(mode=0o755)
            local.chmod(0o755)
            subprocess.run([sys.executable, str(root / "prepare.py")], check=True, capture_output=True)

            self.assertEqual(stat.S_IMODE(local.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((local / "realm.json").stat().st_mode), 0o644)
            for name in ["qualification.env", "credentials.json", "database.env", "keycloak.env"]:
                self.assertEqual(stat.S_IMODE((local / name).stat().st_mode), 0o600, name)

            original = (local / "realm.json").read_bytes()
            rerun = subprocess.run([sys.executable, str(root / "prepare.py")], capture_output=True)
            self.assertNotEqual(rerun.returncode, 0)
            self.assertEqual((local / "realm.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
