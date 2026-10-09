#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export KUBECONFIG="$task_root/.local/kind.kubeconfig"
mkdir -p "$task_root/.local"
case "${1:-}" in
  create)
    docker info >/dev/null
    if kind get clusters | rg -qx cc-contract; then
      kind export kubeconfig --name cc-contract --kubeconfig "$KUBECONFIG"
    else
      kind create cluster --name cc-contract --config "$task_root/infrastructure/kind/cluster.yaml" --kubeconfig "$KUBECONFIG" --wait 180s
    fi
    bash "$0" check
    ;;
  check)
    kubectl --context kind-cc-contract wait --for=condition=Ready nodes --all --timeout=180s
    kubectl --context kind-cc-contract get nodes -o json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert len(d["items"])==3; assert sum(n["metadata"]["labels"].get("cc-contract/role")=="cpu-worker" for n in d["items"])==2; print("three nodes, two CPU workers verified")'
    kubectl --context kind-cc-contract get pods -A -o wide
    ;;
  collect)
    kind export logs --name cc-contract "${2:?artifact directory required}"
    ;;
  destroy)
    kind delete cluster --name cc-contract
    ;;
  *) echo 'usage: kind.sh create|check|collect DIRECTORY|destroy' >&2; exit 2 ;;
esac
