#!/usr/bin/env python3
"""Deploy the same candidate into an already-created isolated kind test cluster.

Requires the pinned Calico/NGINX setup described in README. No production
context, secret, realm or deployment is selected. Does not change HTTPS routing.
"""

import json
import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
local = root / "deploy/oidc/.local"
kubeconfig = local / "kubeconfig"
compose = ["docker", "compose", "-f", str(root / "deploy/oidc/compose.yml")]
kubectl = ["kubectl", "--kubeconfig", str(kubeconfig)]


def run(*args, data=None):
    return subprocess.run(args, input=data, check=True, capture_output=True, cwd=root).stdout


def apply(document):
    return run(*kubectl, "apply", "-f", "-", data=json.dumps(document).encode())


def management(code):
    output = run(*compose, "exec", "-T", "web", "python", "/label-studio/label_studio/manage.py", "shell", "-c", code)
    return output.decode().strip().splitlines()[-1]


def container_ip(name):
    return (
        run("docker", "inspect", name, "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}")
        .decode()
        .strip()
    )


os.umask(0o077)
assert run(*kubectl, "config", "current-context").decode().strip() == "kind-ls-oidc-qualification"
env = dict(line.split("=", 1) for line in (local / "qualification.env").read_text().splitlines() if "=" in line)
apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "labeling"}})
secret = management("from django.conf import settings; print(settings.SECRET_KEY)")
apply(
    {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "ls-oidc-secrets", "namespace": "labeling"},
        "stringData": {
            "SECRET_KEY": secret,
            "POSTGRE_PASSWORD": env["POSTGRE_PASSWORD"],
            "LS_OIDC_CLIENT_SECRET": env["LS_OIDC_CLIENT_SECRET"],
        },
    }
)
for name, directory in [("ls-test-trust", local / "trust.pem"), ("ls-test-fixture", root / "fixtures/oidc")]:
    document = json.loads(
        run(
            *kubectl,
            "create",
            "configmap",
            name,
            "-n",
            "labeling",
            "--from-file=" + str(directory),
            "--dry-run=client",
            "-o",
            "json",
        )
    )
    apply(document)

dns = json.loads(run(*kubectl, "get", "configmap", "coredns", "-n", "kube-system", "-o", "json"))
if "keycloak.localhost" not in dns["data"]["Corefile"]:
    dns["data"]["Corefile"] = dns["data"]["Corefile"].replace(
        "    kubernetes ",
        "    hosts {\n        "
        + container_ip("ls-oidc-qualification-ingress-1")
        + " keycloak.localhost labels.localhost machine.localhost\n        fallthrough\n    }\n    kubernetes ",
        1,
    )
    apply(dns)
run(*kubectl, "rollout", "restart", "deployment/coredns", "-n", "kube-system")
run(*kubectl, "label", "namespace", "ingress-nginx", "labeling-ingress=allowed", "--overwrite")
apply(
    {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "ls-identity-headers", "namespace": "ingress-nginx"},
        "data": {"X-Forwarded-User": "", "X-Remote-User": "", "Remote-User": ""},
    }
)
run(
    *kubectl,
    "patch",
    "configmap",
    "ingress-nginx-controller",
    "-n",
    "ingress-nginx",
    "--type",
    "merge",
    "-p",
    json.dumps(
        {
            "data": {
                "use-forwarded-headers": "true",
                "proxy-set-headers": "ingress-nginx/ls-identity-headers",
                "error-log-level": "crit",
                "log-format-upstream": "$remote_addr $host $request_method $uri $status $request_time",
            }
        }
    ),
)

source = (
    (root / "deploy/oidc/kubernetes.yaml")
    .read_text()
    .replace("${CANDIDATE_IMAGE}", "label-studio-oidc:candidate")
    .replace("${RELEASE_ID}", "test")
)
(local / "kind-source.yaml").write_text(source)
raw = run(
    *kubectl,
    "create",
    "--dry-run=client",
    "--validate=false",
    "-f",
    str(local / "kind-source.yaml"),
    "-o",
    "json",
).decode()
documents = []
decoder = json.JSONDecoder()
while raw.strip():
    raw = raw.lstrip()
    document, offset = decoder.raw_decode(raw)
    documents.extend(document["items"] if document.get("kind") == "List" else [document])
    raw = raw[offset:]
deployment = next(d for d in documents if d["kind"] == "Deployment")
job = next(d for d in documents if d["kind"] == "Job")
release = json.loads(run("docker", "image", "inspect", "label-studio-oidc:candidate"))[0]["Id"].split(":")[1][:12]
job["metadata"]["name"] = "ls-oidc-migrate-" + release
deployment["spec"]["template"]["metadata"].setdefault("annotations", {})["labelstudio.candidate-image"] = release
for document in documents:
    kind = document["kind"]
    if kind == "ConfigMap":
        document["data"].update(
            {
                k: env[k]
                for k in [
                    "LS_OIDC_ISSUER",
                    "LS_OIDC_CLIENT_ID",
                    "LS_OIDC_GROUP",
                    "LS_OIDC_ORGANIZATION_ID",
                    "LS_OIDC_ORIGIN",
                    "LS_MACHINE_ORIGIN",
                ]
            }
        )
        document["data"].update(
            POSTGRE_HOST=container_ip("ls-oidc-qualification-database-1"), REQUESTS_CA_BUNDLE="/trust/trust.pem"
        )
    elif kind in ["Deployment", "Job"]:
        pod = document["spec"]["template"]["spec"]
        for container in pod["containers"]:
            container["image"] = "label-studio-oidc:candidate"
            container["imagePullPolicy"] = "Never"
            container["volumeMounts"] += [
                {"name": "trust", "mountPath": "/trust", "readOnly": True},
                {
                    "name": "fixture",
                    "mountPath": "/label-studio/label_studio/core/static_build/oidc-fixture",
                    "readOnly": True,
                },
            ]
        pod["volumes"] += [
            {"name": "trust", "configMap": {"name": "ls-test-trust"}},
            {"name": "fixture", "configMap": {"name": "ls-test-fixture"}},
        ]
    elif kind == "Ingress":
        machine = document["metadata"]["name"] == "labeling-machine"
        host = "machine.localhost" if machine else "labels.localhost"
        document["spec"]["rules"][0]["host"] = host
        document["spec"]["tls"][0]["hosts"] = [host]
        if machine:
            document["metadata"]["annotations"]["nginx.ingress.kubernetes.io/whitelist-source-range"] = (
                "127.0.0.0/8,172.0.0.0/8,10.0.0.0/8"
            )
    if kind not in ["Deployment", "Job"]:
        apply(document)

seed = json.loads(json.dumps(deployment["spec"]["template"]["spec"]))
seed["restartPolicy"] = "Never"
seed["containers"][0]["name"] = "seed"
seed["containers"][0]["command"] = ["sh", "-c", "sleep 3600"]
seed["containers"][0].pop("readinessProbe", None)
apply(
    {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "ls-media-seed", "namespace": "labeling"}, "spec": seed}
)
run(*kubectl, "wait", "--for=condition=Ready", "pod/ls-media-seed", "-n", "labeling", "--timeout=120s")
seeded = (
    subprocess.run(
        [*kubectl, "exec", "-n", "labeling", "ls-media-seed", "--", "test", "-f", "/label-studio/data/.env"],
        capture_output=True,
    ).returncode
    == 0
)
if not seeded:
    run(
        *kubectl,
        "exec",
        "-i",
        "-n",
        "labeling",
        "ls-media-seed",
        "--",
        "tar",
        "-xf",
        "-",
        "-C",
        "/label-studio/data",
        data=(local / "media.tar").read_bytes(),
    )
run(*kubectl, "delete", "pod", "ls-media-seed", "-n", "labeling", "--wait=true")
apply(job)
run(*kubectl, "wait", "--for=condition=complete", "job/" + job["metadata"]["name"], "-n", "labeling", "--timeout=180s")
apply(deployment)
run(*kubectl, "rollout", "status", "deployment/label-studio", "-n", "labeling", "--timeout=180s")
(local / "kind-rendered.json").write_text(
    json.dumps({"apiVersion": "v1", "kind": "List", "items": documents}, indent=2) + "\n"
)
print("Isolated kind candidate deployed; HTTPS routing remains on Compose until explicit test cutover.")
