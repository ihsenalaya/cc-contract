#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
export KUBECONFIG="$task_root/.local/kind.kubeconfig"
export PYTHONPATH="$task_root/src"
task_run="kind-$(date -u +%Y%m%dT%H%M%SZ)-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:8])')"
task_artifacts="$task_root/.local/integration/$task_run"
mkdir -p "$task_artifacts"
task_image="$(cat .local/images/name)"
export CC_LOCAL_IMAGE="$task_image"
export CC_LOCAL_IMAGE_ID="$(cat .local/images/id)"
export CC_LOCAL_COMMIT="$(git rev-parse HEAD)"
export CC_LOCAL_JOB="$task_run"
python3 scripts/render-local.py > "$task_artifacts/manifests.json"
kind load docker-image "$task_image" --name cc-contract
python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["items"][0]))' < "$task_artifacts/manifests.json" > "$task_artifacts/namespace.json"
kubectl --context kind-cc-contract apply --dry-run=server -f "$task_artifacts/namespace.json"
kubectl --context kind-cc-contract apply -f "$task_artifacts/namespace.json"
kubectl --context kind-cc-contract apply --dry-run=server -f "$task_artifacts/manifests.json" > "$task_artifacts/dry-run.log"
kubectl --context kind-cc-contract apply -f "$task_artifacts/manifests.json" > "$task_artifacts/apply.log"
if kubectl --context kind-cc-contract auth can-i get secrets --as=system:serviceaccount:cc-contract:runner -n cc-contract; then
  echo 'runner unexpectedly has secret access' >&2; exit 1
fi
kubectl --context kind-cc-contract wait --for=condition=complete "job/$task_run" -n cc-contract --timeout=180s
kubectl --context kind-cc-contract get pods -n cc-contract -l "job-name=$task_run" -o json > "$task_artifacts/pods.json"
kubectl --context kind-cc-contract get events -n cc-contract -o json > "$task_artifacts/events.json"
kubectl --context kind-cc-contract get job "$task_run" -n cc-contract -o json > "$task_artifacts/job.json"
for task_pod in $(kubectl --context kind-cc-contract get pods -n cc-contract -l "job-name=$task_run" -o jsonpath='{.items[*].metadata.name}'); do
  kubectl --context kind-cc-contract logs -n cc-contract "$task_pod" > "$task_artifacts/$task_pod.jsonl"
  python3 scripts/verify_jsonl.py "$task_artifacts/$task_pod.jsonl"
done
python3 scripts/verify-integration.py "$task_artifacts"
