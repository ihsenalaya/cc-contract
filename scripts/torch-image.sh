#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
export KUBECONFIG="$task_root/.local/kind.kubeconfig"
export PYTHONPATH="$task_root/src"
mkdir -p .local/torch
task_commit="$(git rev-parse HEAD)"
task_image="cc-contract-torch:$task_commit"
case "${1:-}" in
  build)
    bash scripts/quick-check.sh
    test -z "$(git status --porcelain -- src Dockerfile.torch scripts/requirements-torch.txt .dockerignore)"
    task_commit="$(git rev-parse HEAD)"
    task_image="cc-contract-torch:$task_commit"
    task_context="$(mktemp -d)"
    trap 'rm -rf "$task_context"' EXIT
    git archive "$task_commit" | tar -xf - -C "$task_context"
    docker build --platform linux/amd64 --file "$task_context/Dockerfile.torch" --build-arg "CC_COMMIT=$task_commit" --tag "$task_image" "$task_context"
    rm -rf "$task_context"
    trap - EXIT
    docker image inspect "$task_image" > .local/torch/inspect.json
    docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL --security-opt no-new-privileges "$task_image" > .local/torch/reference.json
    set +e
    docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m "$task_image" components --device cuda > .local/torch/no-device.json
    task_status=$?
    set -e
    test "$task_status" -eq 77
    docker run --rm --network none --entrypoint python "$task_image" -m pip list --format=json > .local/torch/packages.json
    python3 - <<'PY'
import json
from pathlib import Path
p=Path('.local/torch'); r=json.loads((p/'reference.json').read_text()); u=json.loads((p/'no-device.json').read_text())
assert r['verdict']=='PASS' and r['environment']['scope']=='REAL_TORCH_CPU_ONLY' and len(r['records'])==18
assert r['tiny_transformer_fixture']['verdict']=='PASS' and not r['tiny_transformer_fixture']['real_Qwen2_5_7B_executed']
assert u['verdict']=='UNSUPPORTED' and not u['environment']['gpu_executed']
PY
    printf '%s\n' "$task_image" > .local/torch/name
    ;;
  kind)
    export CC_LOCAL_IMAGE="$(cat .local/torch/name)"
    export CC_LOCAL_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$CC_LOCAL_IMAGE")"
    # Load only workers; the control plane does not execute scientific tests.
    kind load docker-image "$CC_LOCAL_IMAGE" --name cc-contract --nodes cc-contract-worker,cc-contract-worker2
    task_base="torch-$(date -u +%Y%m%dt%H%M%Sz)-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:6])')"
    task_directory=".local/torch/$task_base"; mkdir -p "$task_directory"
    for task_index in 0 1; do
      export CC_LOCAL_JOB="$task_base-$task_index"
      python3 scripts/render-local.py > "$task_directory/base-$task_index.json"
      python3 - "$task_directory" "$task_index" <<'PY'
import json,sys
from pathlib import Path
d=Path(sys.argv[1]); index=sys.argv[2]; m=json.loads((d/('base-'+index+'.json')).read_text())
j=m['items'][-1]; j['spec'].update({'completions':1,'parallelism':1,'activeDeadlineSeconds':300})
s=j['spec']['template']['spec']; s.pop('topologySpreadConstraints'); s['nodeSelector']['kubernetes.io/hostname']='cc-contract-worker'+('2' if index=='1' else '')
c=s['containers'][0]; c['command']=['/bin/sh','-c']; c['args']=['set -e; python -m cc_contract.torch_workload local-selftest --device cpu; set +e; python -m cc_contract.torch_workload components --device cuda; result=$?; test "$result" -eq 77']
c['resources']={'requests':{'cpu':'100m','memory':'256Mi'},'limits':{'cpu':'1','memory':'768Mi'}}
c['volumeMounts']=[{'name':'temporary','mountPath':'/tmp'}]; s['volumes']=[{'name':'temporary','emptyDir':{'medium':'Memory','sizeLimit':'64Mi'}}]
(d/('manifests-'+index+'.json')).write_text(json.dumps(m,indent=2)+'\n')
PY
      kubectl --context kind-cc-contract apply --dry-run=server -f "$task_directory/manifests-$task_index.json" > "$task_directory/dry-run-$task_index.log"
      kubectl --context kind-cc-contract apply -f "$task_directory/manifests-$task_index.json" > "$task_directory/apply-$task_index.log"
      kubectl --context kind-cc-contract wait --for=condition=complete "job/$CC_LOCAL_JOB" -n cc-contract --timeout=320s
      kubectl --context kind-cc-contract get pods -n cc-contract -l "job-name=$CC_LOCAL_JOB" -o json > "$task_directory/pods-$task_index.json"
      task_pod="$(kubectl --context kind-cc-contract get pods -n cc-contract -l "job-name=$CC_LOCAL_JOB" -o jsonpath='{.items[0].metadata.name}')"
      kubectl --context kind-cc-contract logs -n cc-contract "$task_pod" > "$task_directory/output-$task_index.jsonl"
    done
    python3 - "$task_directory" <<'PY'
import hashlib,json,sys
from pathlib import Path
d=Path(sys.argv[1]); workers=[]
for index in (0,1):
 pods=json.loads((d/f'pods-{index}.json').read_text())['items']; assert len(pods)==1
 pod=pods[0]; assert pod['status']['phase']=='Succeeded'; workers.append(pod['spec']['nodeName'])
 text=(d/f'output-{index}.jsonl').read_text(); r,end=json.JSONDecoder().raw_decode(text); u=json.loads(text[end:])
 assert r['verdict']=='PASS' and r['environment']['scope']=='REAL_TORCH_CPU_ONLY' and len(r['records'])==18
 assert r['tiny_transformer_fixture']['verdict']=='PASS' and not r['tiny_transformer_fixture']['real_Qwen2_5_7B_executed']
 assert u['verdict']=='UNSUPPORTED' and not u['environment']['gpu_executed']
assert len(set(workers))==2
i=json.loads(Path('.local/torch/inspect.json').read_text())[0]
r={'scope':'REAL_TORCH_CPU_COMPONENTS_AND_RANDOM_TINY_TRANSFORMER_FIXTURE','verified':True,'gpu_executed':False,'real_Qwen2_5_7B_executed':False,'git_commit':i['Config']['Labels']['org.opencontainers.image.revision'],'image_id':i['Id'],'workers':workers,'component_records_per_worker':18,'hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in d.iterdir() if p.is_file()}}
(d/'verified.json').write_text(json.dumps(r,indent=2)+'\n'); Path('.local/torch/kind-verified.json').write_text(json.dumps(r,indent=2)+'\n'); print(json.dumps(r,indent=2))
PY
    ;;
  publish)
    task_image="$(cat .local/torch/name)"
    python3 - <<'PY'
import json,subprocess
from pathlib import Path
p=Path('.local/torch'); i=json.loads((p/'inspect.json').read_text())[0]; g=json.loads((p/'kind-verified.json').read_text())
assert g['verified'] and g['image_id']==i['Id'] and g['git_commit']==i['Config']['Labels']['org.opencontainers.image.revision']
assert i['Id']==subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',(p/'name').read_text().strip()],text=True).strip()
assert not subprocess.check_output(['git','status','--porcelain','--','src','Dockerfile.torch','scripts/requirements-torch.txt','.dockerignore'],text=True).strip()
assert i['Config']['User']=='10001:10001'
PY
    task_build_commit="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$task_image")"
    task_remote="ghcr.io/ihsenalaya/cc-contract-torch:$task_build_commit"
    docker tag "$task_image" "$task_remote"; docker push "$task_remote" | tee .local/torch/push.log
    docker buildx imagetools inspect "$task_remote" --format '{{json .Manifest}}' > .local/torch/registry.json
    python3 - <<'PY'
import json
from pathlib import Path
p=Path('.local/torch'); digest=json.loads((p/'registry.json').read_text())['digest']
(p/'remote-digest').write_text('ghcr.io/ihsenalaya/cc-contract-torch@'+digest+'\n'); print((p/'remote-digest').read_text())
PY
    ;;
  *) echo 'usage: torch-image.sh build|kind|publish' >&2; exit 2 ;;
esac
