"""Prove update automation retains fork CI before opening an upstream PR."""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("upstream_review", Path(__file__).with_name("upstream_review.py"))
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class WorkflowRetentionTests(unittest.TestCase):
    def test_changed_added_and_deleted_upstream_workflows_stay_inactive(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)

                def git(*args):
                    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.PIPE).strip()

                git("init", "--quiet")
                git("config", "user.name", "Workflow test")
                git("config", "user.email", "workflow@example.invalid")
                workflows = Path(".github/workflows")
                workflows.mkdir(parents=True)
                (workflows / "keep.yml").write_text("fork-owned qualification\n")
                (workflows / "retained.yml").write_text("guarded upstream job\n")
                Path("app.py").write_text("old release\n")
                git("add", ".")
                git("commit", "--quiet", "-m", "fork baseline")

                (workflows / "keep.yml").write_text("upstream publication\n")
                (workflows / "retained.yml").unlink()
                (workflows / "publish.yml").write_text("new upstream deployment\n")
                Path("app.py").write_text("new reviewed-source candidate\n")
                git("add", ".")  # State produced by a successful --no-commit merge.

                changed = review.preserve_fork_workflows()
                self.assertEqual(
                    set(changed),
                    {str(workflows / name) for name in ["keep.yml", "retained.yml", "publish.yml"]},
                )
                self.assertEqual((workflows / "keep.yml").read_text(), "fork-owned qualification\n")
                self.assertEqual((workflows / "retained.yml").read_text(), "guarded upstream job\n")
                self.assertFalse((workflows / "publish.yml").exists())
                self.assertEqual(git("diff", "HEAD", "--", str(workflows)), "")
                self.assertEqual(Path("app.py").read_text(), "new reviewed-source candidate\n")
                self.assertNotEqual(git("diff", "--cached", "--", "app.py"), "")
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
