"""Qualify one locally built continuity image serially on the two Kind workers."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def command(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, timeout=180, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.environ["KUBECONFIG"] = str(ROOT / ".local/kind.kubeconfig")
    inspection = json.loads(command(["docker", "image", "inspect", args.image]).stdout)[0]
    (args.output / "image-inspect.json").write_text(json.dumps(inspection, indent=2) + "\n")
    command(["kind", "load", "docker-image", args.image, "--name", "cc-contract",
             "--nodes", "cc-contract-worker,cc-contract-worker2"])
    namespace = "cc-continuity-" + uuid4().hex[:8]
    namespace_doc = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace,
                     "labels": {"pod-security.kubernetes.io/enforce": "restricted"}}}
    command(["kubectl", "apply", "-f", "-"], input=json.dumps(namespace_doc).encode())
    receipts = []
    try:
        sa = {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": "runner", "namespace": namespace},
              "automountServiceAccountToken": False}
        command(["kubectl", "apply", "-f", "-"], input=json.dumps(sa).encode())
        denied = subprocess.run(["kubectl", "auth", "can-i", "get", "secrets", "--namespace", namespace,
                                 "--as", f"system:serviceaccount:{namespace}:runner"], capture_output=True, timeout=30)
        if denied.returncode != 1 or denied.stdout.strip() != b"no":
            raise ValueError("Runner API permission not denied")
        (args.output / "rbac.txt").write_bytes(denied.stdout + denied.stderr)
        wrapper = """import json, pathlib, subprocess, sys
from cc_contract.continuity_pilot import inputs
code=subprocess.run([sys.executable,'-m','cc_contract.continuity_pilot','--output','/tmp/results'],capture_output=True)
if code.returncode: raise RuntimeError(code.stderr.decode())
expected,packets=inputs(71000)
proc=subprocess.run(['/usr/local/bin/cc-continuity-worker','C1','1'],input=b''.join(packets),capture_output=True,timeout=10)
gpu=json.loads(proc.stdout)
if proc.returncode or gpu.get('execution_status')!='UNSUPPORTED': raise RuntimeError('CPU node must report unsupported CUDA')
print(json.dumps({'summary':json.loads(pathlib.Path('/tmp/results/summary.json').read_text()),'runs':pathlib.Path('/tmp/results/runs.jsonl').read_text(),'cuda_no_device':gpu}))
"""
        for index, node in enumerate(("cc-contract-worker", "cc-contract-worker2")):
            name = "model-" + str(index)
            pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": namespace},
                   "spec": {"restartPolicy": "Never", "activeDeadlineSeconds": 60,
                            "serviceAccountName": "runner", "automountServiceAccountToken": False,
                            "nodeSelector": {"kubernetes.io/hostname": node},
                            "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
                                                "seccompProfile": {"type": "RuntimeDefault"}},
                            "containers": [{"name": "model", "image": args.image, "imagePullPolicy": "Never",
                                            "command": ["python3", "-c", wrapper],
                                            "resources": {"requests": {"cpu": "100m", "memory": "64Mi"},
                                                          "limits": {"cpu": "1", "memory": "256Mi"}},
                                            "securityContext": {"allowPrivilegeEscalation": False,
                                                                "readOnlyRootFilesystem": True,
                                                                "capabilities": {"drop": ["ALL"]}},
                                            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}]}],
                            "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "16Mi"}}]}}
            data = json.dumps(pod).encode()
            (args.output / f"pod-{index}.json").write_bytes(data)
            command(["kubectl", "apply", "--dry-run=server", "-f", "-"], input=data)
            command(["kubectl", "apply", "-f", "-"], input=data)
            deadline = time.monotonic() + 90
            while True:
                state = json.loads(command(["kubectl", "get", "pod", name, "-n", namespace, "-o", "json"]).stdout)
                if state["status"]["phase"] in ("Succeeded", "Failed") or time.monotonic() > deadline:
                    break
                time.sleep(1)
            (args.output / f"state-{index}.json").write_text(json.dumps(state, indent=2) + "\n")
            log = command(["kubectl", "logs", name, "-n", namespace]).stdout
            (args.output / f"log-{index}.json").write_bytes(log)
            if state["status"]["phase"] != "Succeeded":
                raise ValueError("Kind pod did not succeed")
            result = json.loads(log)
            if result["summary"]["actual_runs"] != 50 or result["summary"]["real_cuda_validated"]:
                raise ValueError("CPU summary scope incorrect")
            metrics = result["summary"]["metrics"]
            if any(x["model_success"] != 10 or x["cuda_success"] != 0 or x["missed"] != 0 for x in metrics):
                raise ValueError("Model qualification failed")
            if metrics[0]["false_positives"] != 0 or any(x["detected"] != 10 for x in metrics[1:]):
                raise ValueError("Model detection check failed")
            receipts.append(dict(node=node, log_sha256=hashlib.sha256(log).hexdigest(),
                                 actual_runs=50, cuda="UNSUPPORTED", image_id=state["status"]["containerStatuses"][0]["imageID"]))
            print(node + ": 50 CPU-model cases and CUDA no-device handling verified", flush=True)
        receipt = dict(completed_utc=datetime.now(timezone.utc).isoformat(), state="PASS_KIND_CPU_ONLY",
                       image=args.image, local_image_id=inspection["Id"], receipts=receipts,
                       rbac_secrets_denied=True, real_cuda_validated=False)
        (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    finally:
        command(["kubectl", "delete", "namespace", namespace, "--wait=true", "--timeout=90s"])


if __name__ == "__main__":
    main()
