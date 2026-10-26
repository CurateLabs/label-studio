"""Stage reviewed release/security updates, open a draft PR and dispatch tests.

Never deploy or merge a PR. --check performs read-only notification discovery.
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout.strip()


parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
options = parser.parse_args()
release = json.loads(run("gh", "api", "repos/HumanSignal/label-studio/releases/latest"))
tag = release["tag_name"]
pending = []
for repository, baseline in [
    ("HumanSignal/label-studio", "upstream-advisories.json"),
    ("authlib/authlib", "authlib-advisories.json"),
]:
    reviewed = {
        (item["ghsa_id"], item.get("updated_at"))
        for item in json.loads((Path(__file__).parent / "evidence" / baseline).read_text())
    }
    advisories = json.loads(run("gh", "api", f"repos/{repository}/security-advisories?per_page=100"))
    pending.extend(
        {
            "repository": repository,
            "ghsa_id": item["ghsa_id"],
            "severity": item["severity"],
            "updated_at": item.get("updated_at"),
            "url": item["html_url"],
            "vulnerabilities": item["vulnerabilities"],
        }
        for item in advisories
        if (item["ghsa_id"], item.get("updated_at")) not in reviewed
    )
new_release = tag != "1.23.2"
if options.check or not (new_release or pending):
    print(
        json.dumps(
            {
                "upstream_release": tag,
                "new_release": new_release,
                "new_or_updated_advisories": len(pending),
                "deployment": False,
            }
        )
    )
    raise SystemExit(0)
fingerprint = hashlib.sha256(json.dumps(pending, sort_keys=True).encode()).hexdigest()[:12]
branch = "upstream-review/" + tag if new_release else "security-review/" + fingerprint
if json.loads(run("gh", "pr", "list", "--head", branch, "--state", "all", "--json", "url")):
    raise SystemExit("Reviewed update work already exists for this notification")
run("git", "config", "user.name", "Community update bot")
run("git", "config", "user.email", "community-update@users.noreply.github.com")
run("git", "switch", "-c", branch)
sha = "df96d79183156e556d91825d15fa7721f1145e1a"
conflicts = []
if new_release:
    run("git", "fetch", "https://github.com/HumanSignal/label-studio.git", "refs/tags/" + tag)
    sha = run("git", "rev-parse", "FETCH_HEAD")
    merge = subprocess.run(["git", "merge", "--no-commit", "--no-ff", sha], capture_output=True, text=True)
    if merge.returncode:
        conflicts = run("git", "diff", "--name-only", "--diff-filter=U").splitlines()
        run("git", "merge", "--abort")
candidate = {
    "release": tag,
    "sha": sha,
    "release_url": release["html_url"],
    "conflicts": conflicts,
    "security_review": pending,
    "status": "UNQUALIFIED; retain deployed image; review routes, dependencies, license and immutable image digest",
}
Path("deploy/oidc/upstream-candidate.json").write_text(json.dumps(candidate, indent=2) + "\n")
run("git", "add", "-A")
run("git", "commit", "-m", f"chore: review Community {tag} release and security updates")
run("git", "push", "origin", branch)
with tempfile.NamedTemporaryFile(mode="w", suffix=".md") as body:
    body.write(
        f"Community {tag} ({sha}) requires release/security review. This draft does not deploy.\n\n"
        "Review merge conflicts and new advisories, source/image correspondence, dependency locks, "
        "resolved routes/authenticators, automatic credentials and native editor behavior. Run all OIDC "
        "qualification and restore checks before promotion. Preserve the previous image and compatible schema.\n"
    )
    body.flush()
    base = json.loads(run("gh", "repo", "view", "--json", "defaultBranchRef"))["defaultBranchRef"]["name"]
    run(
        "gh",
        "pr",
        "create",
        "--draft",
        "--base",
        base,
        "--head",
        branch,
        "--title",
        f"Review Community {tag} release and security updates",
        "--body-file",
        body.name,
    )
# GITHUB_TOKEN-created PR events do not trigger other workflows automatically.
run("gh", "workflow", "run", "oidc-qualification.yml", "--ref", branch)
