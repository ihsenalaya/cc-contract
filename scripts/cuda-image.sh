#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
export KUBECONFIG="$task_root/.local/kind.kubeconfig"
export PYTHONPATH="$task_root/src"
mkdir -p .local/cuda
task_commit="$(git rev-parse HEAD)"
task_image="cc-contract-cuda:$task_commit"
case "${1:-}" in
  build)
    bash scripts/quick-check.sh
    test -z "$(git status --porcelain -- src/cuda Dockerfile.cuda .dockerignore)"
    task_commit="$(git rev-parse HEAD)"
    task_image="cc-contract-cuda:$task_commit"
    task_context="$(mktemp -d)"
    trap 'rm -rf "$task_context"' EXIT
    git archive "$task_commit" | tar -xf - -C "$task_context"
    docker build --platform linux/amd64 --file "$task_context/Dockerfile.cuda" --build-arg "CC_COMMIT=$task_commit" --tag "$task_image" "$task_context"
    rm -rf "$task_context"
    trap - EXIT
    docker image inspect "$task_image" > .local/cuda/inspect.json
    docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges "$task_image" --cpu-reference-tests > .local/cuda/reference.json
    set +e
    docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges "$task_image" > .local/cuda/no-device.json
    task_status=$?
    set -e
    test "$task_status" -eq 77
    python3 - <<'PY'
import json
from pathlib import Path
p=Path('.local/cuda'); reference=json.loads((p/'reference.json').read_text()); missing=json.loads((p/'no-device.json').read_text())
assert reference['scope']=='CPU_REFERENCE_ONLY' and not reference['gpu_executed'] and reference['verdict']=='PASS'
assert missing['verdict']=='UNSUPPORTED' and not missing['gpu_executed']
PY
    printf '%s\n' "$task_image" > .local/cuda/name
    ;;
  kind)
    export CC_LOCAL_IMAGE="$(cat .local/cuda/name)"
    export CC_LOCAL_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$CC_LOCAL_IMAGE")"
    export CC_LOCAL_JOB="cuda-$(date -u +%Y%m%dt%H%M%Sz)-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:8])')"
    task_directory=".local/cuda/$CC_LOCAL_JOB"
    mkdir -p "$task_directory"
    python3 scripts/render-local.py > "$task_directory/base.json"
    python3 - "$task_directory" <<'PY'
import json,sys
from pathlib import Path
d=Path(sys.argv[1]); m=json.loads((d/'base.json').read_text()); c=m['items'][-1]['spec']['template']['spec']['containers'][0]
c['command']=['/bin/bash','-c']; c['args']=['set -e; /usr/local/bin/cc-qualification --cpu-reference-tests; set +e; /usr/local/bin/cc-qualification; result=$?; test "$result" -eq 77']
(d/'manifests.json').write_text(json.dumps(m,indent=2)+'\n')
PY
    kind load docker-image "$CC_LOCAL_IMAGE" --name cc-contract
    kubectl --context kind-cc-contract apply --dry-run=server -f "$task_directory/manifests.json" > "$task_directory/dry-run.log"
    kubectl --context kind-cc-contract apply -f "$task_directory/manifests.json" > "$task_directory/apply.log"
    kubectl --context kind-cc-contract wait --for=condition=complete "job/$CC_LOCAL_JOB" -n cc-contract --timeout=180s
    kubectl --context kind-cc-contract get pods -n cc-contract -l "job-name=$CC_LOCAL_JOB" -o json > "$task_directory/pods.json"
    for task_pod in $(kubectl --context kind-cc-contract get pods -n cc-contract -l "job-name=$CC_LOCAL_JOB" -o jsonpath='{.items[*].metadata.name}'); do
      kubectl --context kind-cc-contract logs -n cc-contract "$task_pod" > "$task_directory/$task_pod.jsonl"
    done
    python3 - "$task_directory" <<'PY'
import hashlib,json,sys
from pathlib import Path
d=Path(sys.argv[1]); pods=json.loads((d/'pods.json').read_text())['items']; assert len(pods)==2
assert len({p['spec']['nodeName'] for p in pods})==2
for pod in pods:
 assert pod['status']['phase']=='Succeeded'
 rows=[json.loads(x) for x in (d/(pod['metadata']['name']+'.jsonl')).read_text().splitlines()]
 assert len(rows)==2 and rows[0]['scope']=='CPU_REFERENCE_ONLY' and rows[0]['verdict']=='PASS'
 assert rows[1]['verdict']=='UNSUPPORTED' and all(not r['gpu_executed'] for r in rows)
inspection=json.loads(Path('.local/cuda/inspect.json').read_text())[0]
result={'scope':'CPU_REFERENCE_AND_NO_GPU_REJECTION_ONLY','verified':True,'git_commit':inspection['Config']['Labels']['org.opencontainers.image.revision'],'image_id':inspection['Id'],'workers':[p['spec']['nodeName'] for p in pods],'hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in d.iterdir() if p.is_file()}}
(d/'verified.json').write_text(json.dumps(result,indent=2)+'\n')
Path('.local/cuda/kind-verified.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result,indent=2))
PY
    ;;
  publish)
    task_image="$(cat .local/cuda/name)"
    python3 - <<'PY'
import json,subprocess
from pathlib import Path
p=Path('.local/cuda'); i=json.loads((p/'inspect.json').read_text())[0]; g=json.loads((p/'kind-verified.json').read_text())
assert g['verified'] and g['image_id']==i['Id'] and g['git_commit']==i['Config']['Labels']['org.opencontainers.image.revision']
assert not subprocess.check_output(['git','status','--porcelain','--','src/cuda','Dockerfile.cuda','.dockerignore'],text=True).strip()
assert i['Config']['User']=='10001:10001'
PY
    task_build_commit="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$task_image")"
    task_remote="ghcr.io/ihsenalaya/cc-contract-cuda:$task_build_commit"
    docker tag "$task_image" "$task_remote"
    docker push "$task_remote" | tee .local/cuda/push.log
    docker buildx imagetools inspect "$task_remote" --format '{{json .Manifest}}' > .local/cuda/registry.json
    python3 - <<'PY'
import json
from pathlib import Path
p=Path('.local/cuda'); digest=json.loads((p/'registry.json').read_text())['digest']
(p/'remote-digest').write_text('ghcr.io/ihsenalaya/cc-contract-cuda@'+digest+'\n'); print((p/'remote-digest').read_text())
PY
    ;;
  *) echo 'usage: cuda-image.sh build|kind|publish' >&2; exit 2 ;;
esac
