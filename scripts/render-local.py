"""Kubernetes JSON is YAML-compatible; generate explicit immutable test inputs."""
import json
import os

ns = "cc-contract"
job_name = os.environ["CC_LOCAL_JOB"]
container = {"name": "runner", "image": os.environ["CC_LOCAL_IMAGE"], "imagePullPolicy": "Never", "args": ["selftest", "--emit-records"], "env": [{"name": "CC_BUILD_IMAGE_ID", "value": os.environ["CC_LOCAL_IMAGE_ID"]}, {"name": "CC_IMAGE_DIGEST", "value": "LOCAL_IMAGE_UNPUBLISHED"}], "resources": {"requests": {"cpu": "50m", "memory": "32Mi"}, "limits": {"cpu": "250m", "memory": "128Mi"}}, "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}}
items = [
    {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns, "labels": {"pod-security.kubernetes.io/enforce": "restricted", "pod-security.kubernetes.io/enforce-version": "v1.35"}}},
    {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": "runner", "namespace": ns}, "automountServiceAccountToken": False},
    {"apiVersion": "v1", "kind": "ResourceQuota", "metadata": {"name": "local-budget", "namespace": ns}, "spec": {"hard": {"requests.cpu": "1", "requests.memory": "512Mi", "limits.cpu": "2", "limits.memory": "1Gi", "pods": "8"}}},
    {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": job_name, "namespace": ns}, "spec": {"completions": 2, "parallelism": 2, "completionMode": "Indexed", "backoffLimit": 0, "activeDeadlineSeconds": 180, "template": {"metadata": {"labels": {"app": job_name}}, "spec": {"restartPolicy": "Never", "serviceAccountName": "runner", "automountServiceAccountToken": False, "nodeSelector": {"cc-contract/role": "cpu-worker"}, "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001, "seccompProfile": {"type": "RuntimeDefault"}}, "topologySpreadConstraints": [{"maxSkew": 1, "topologyKey": "kubernetes.io/hostname", "whenUnsatisfiable": "DoNotSchedule", "labelSelector": {"matchLabels": {"app": job_name}}}], "containers": [container]}}}}
]
print(json.dumps({"apiVersion": "v1", "kind": "List", "items": items}, indent=2))
