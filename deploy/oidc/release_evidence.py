"""Record immutable local candidate identity. A manifest is evidence, not approval."""

import hashlib
import json
import subprocess
from pathlib import Path


def run(*args):
    return subprocess.check_output(args, text=True).strip()


root = Path(__file__).parent
image = json.loads(run("docker", "image", "inspect", "label-studio-oidc:candidate"))[0]
source_revision = image["Config"]["Labels"]["org.opencontainers.image.revision"]
metadata_file = root / ".local/build-metadata.json"
metadata = json.loads(metadata_file.read_text()) if metadata_file.exists() else {}
image_paths = [
    "label_studio",
    "web",
    "deploy/oidc/Dockerfile",
    "deploy/oidc/requirements.lock",
    "deploy/oidc/uwsgi.ini",
    "pyproject.toml",
    "poetry.lock",
    ".dockerignore",
    "LICENSE",
    "NOTICE",
]
evidence = {
    "qualification": "UNQUALIFIED until the complete operator acceptance record passes",
    "upstream_tag": "1.23.2",
    "upstream_sha": "df96d79183156e556d91825d15fa7721f1145e1a",
    "fork_sha": source_revision,
    "checkout_sha_at_capture": run("git", "rev-parse", "HEAD"),
    "working_tree_dirty": bool(run("git", "status", "--porcelain")),
    "image_sources_match_fork_sha": not bool(run("git", "diff", source_revision, "--", *image_paths)),
    "base_digest": "sha256:afcc516a22775a39d0d66f4c2ddc95d01be3e3d3862b21fcf4f9de34b4ad4e12",
    "docker_image_id": image["Id"],
    "image_manifest_digest": image.get("Descriptor", {}).get("digest"),
    "image_config_digest": metadata.get("containerimage.config.digest"),
    "repository_digests": image.get("RepoDigests", []),
    "build_revision": image["Config"]["Labels"].get("org.opencontainers.image.revision"),
    "overlay_lock_sha256": hashlib.sha256((root / "requirements.lock").read_bytes()).hexdigest(),
    "architecture": image["Architecture"],
    "authlib": "1.9.1",
    "joserfc": "1.7.7",
    "frontend_lock_sha256": hashlib.sha256(Path("web/yarn.lock").read_bytes()).hexdigest(),
    "frontend_node_image": "node@sha256:de170b39439eb0e5a3444ad7d60b015614a381e10fecae2e30ec9e735122f38d",
}
(root / "evidence/release.json").write_text(json.dumps(evidence, indent=2) + "\n")
packages = run(
    "docker",
    "run",
    "--rm",
    "--entrypoint",
    "python",
    "label-studio-oidc:candidate",
    "-c",
    'import importlib.metadata as m,json; print(json.dumps({d.metadata["Name"]:d.version for d in m.distributions()},sort_keys=True,indent=2))',
)
(root / "evidence/candidate-packages.json").write_text(packages + "\n")
apk = run("docker", "run", "--rm", "--entrypoint", "apk", "label-studio-oidc:candidate", "info", "-vv")
(root / "evidence/candidate-apk.txt").write_text(apk + "\n")
print(json.dumps(evidence, indent=2))
