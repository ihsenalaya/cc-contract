#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
export KUBECONFIG="$task_root/.local/kind.kubeconfig"
export PYTHONPATH="$task_root/src"
mkdir -p .local/ir
task_commit="$(git rev-parse HEAD)"
task_image="cc-contract-ir:$task_commit"
case "${1:-}" in
  build)
    bash scripts/quick-check.sh
    test -z "$(git status --porcelain -- src Dockerfile.ir .dockerignore)"
    task_commit="$(git rev-parse HEAD)"
    task_image="cc-contract-ir:$task_commit"
    task_context="$(mktemp -d)"
    trap 'rm -rf "$task_context"' EXIT
    git archive "$task_commit" | tar -xf - -C "$task_context"
    docker build --platform linux/amd64 --file "$task_context/Dockerfile.ir" --build-arg "CC_COMMIT=$task_commit" --tag "$task_image" "$task_context"
    rm -rf "$task_context"
    trap - EXIT
    docker image inspect "$task_image" > .local/ir/inspect.json
    docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges "$task_image" qualify --backend native-reference > .local/ir/reference.json
    set +e
    docker run --rm --network none --read-only --entrypoint /usr/local/bin/cc-ir-worker "$task_image" > .local/ir/no-device.json
    task_status=$?
    set -e
    test "$task_status" -eq 77
    python3 - <<'PY'
import json
from pathlib import Path
p=Path('.local/ir'); r=json.loads((p/'reference.json').read_text()); u=json.loads((p/'no-device.json').read_text())
assert r['scope']=='CPU_NATIVE_REFERENCE_ONLY' and not r['gpu_executed'] and r['counts']=={'PASS':96}
assert u['verdict']=='UNSUPPORTED' and not u['gpu_executed']
PY
    printf '%s\n' "$task_image" > .local/ir/name
    ;;
  kind)
    export CC_LOCAL_IMAGE="$(cat .local/ir/name)"
    export CC_LOCAL_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$CC_LOCAL_IMAGE")"
    export CC_LOCAL_JOB="ir-$(date -u +%Y%m%dt%H%M%Sz)-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:8])')"
    task_directory=".local/ir/$CC_LOCAL_JOB"
    mkdir -p "$task_directory"
    python3 scripts/render-local.py > "$task_directory/base.json"
    python3 - "$task_directory" <<'PY'
import json,sys
from pathlib import Path
d=Path(sys.argv[1]); m=json.loads((d/'base.json').read_text()); c=m['items'][-1]['spec']['template']['spec']['containers'][0]
c['command']=['/bin/sh','-c']; c['args']=['set -e; python3 -m cc_contract.runner qualify --backend native-reference; set +e; /usr/local/bin/cc-ir-worker; result=$?; test "$result" -eq 77']
c['resources']['limits']['memory']='256Mi'
(d/'manifests.json').write_text(json.dumps(m,indent=2)+'\n')
PY
    kind load docker-image "$CC_LOCAL_IMAGE" --name cc-contract
    kubectl --context kind-cc-contract apply --dry-run=server -f "$task_directory/manifests.json" > "$task_directory/dry-run.log"
    kubectl --context kind-cc-contract apply -f "$task_directory/manifests.json" > "$task_directory/apply.log"
    kubectl --context kind-cc-contract wait --for=condition=complete "job/$CC_LOCAL_JOB" -n cc-contract --timeout=240s
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
 text=(d/(pod['metadata']['name']+'.jsonl')).read_text(); dec=json.JSONDecoder(); r,end=dec.raw_decode(text)
 u=json.loads(text[end:]); assert r['counts']=={'PASS':96} and r['scope']=='CPU_NATIVE_REFERENCE_ONLY'
 assert u['verdict']=='UNSUPPORTED' and not r['gpu_executed'] and not u['gpu_executed']
i=json.loads(Path('.local/ir/inspect.json').read_text())[0]
r={'scope':'CPU_NATIVE_REFERENCE_AND_NO_GPU_REJECTION','verified':True,'git_commit':i['Config']['Labels']['org.opencontainers.image.revision'],'image_id':i['Id'],'workers':[p['spec']['nodeName'] for p in pods],'cases_per_worker':96,'hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in d.iterdir() if p.is_file()}}
(d/'verified.json').write_text(json.dumps(r,indent=2)+'\n'); Path('.local/ir/kind-verified.json').write_text(json.dumps(r,indent=2)+'\n'); print(json.dumps(r,indent=2))
PY
    ;;
  publish)
    task_image="$(cat .local/ir/name)"
    python3 - <<'PY'
import json,subprocess
from pathlib import Path
p=Path('.local/ir'); i=json.loads((p/'inspect.json').read_text())[0]; g=json.loads((p/'kind-verified.json').read_text())
assert g['verified'] and g['image_id']==i['Id'] and g['git_commit']==i['Config']['Labels']['org.opencontainers.image.revision']
assert i['Id']==subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',(p/'name').read_text().strip()],text=True).strip()
assert not subprocess.check_output(['git','status','--porcelain','--','src','Dockerfile.ir','.dockerignore'],text=True).strip()
assert i['Config']['User']=='10001:10001'
PY
    task_build_commit="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$task_image")"
    task_remote="ghcr.io/ihsenalaya/cc-contract-ir:$task_build_commit"
    docker tag "$task_image" "$task_remote"
    docker push "$task_remote" | tee .local/ir/push.log
    docker buildx imagetools inspect "$task_remote" --format '{{json .Manifest}}' > .local/ir/registry.json
    python3 - <<'PY'
import json
from pathlib import Path
p=Path('.local/ir'); digest=json.loads((p/'registry.json').read_text())['digest']
(p/'remote-digest').write_text('ghcr.io/ihsenalaya/cc-contract-ir@'+digest+'\n'); print((p/'remote-digest').read_text())
PY
    ;;
  *) echo 'usage: ir-image.sh build|kind|publish' >&2; exit 2 ;;
esac
