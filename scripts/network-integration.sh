#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
export KUBECONFIG="$task_root/.local/kind.kubeconfig"
export PYTHONPATH="$task_root/src"
export CC_LOCAL_IMAGE="$(cat .local/images/name)"
export CC_LOCAL_IMAGE_ID="$(cat .local/images/id)"
export CC_LOCAL_JOB="net-$(date -u +%Y%m%dt%H%M%Sz)-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:8])')"
task_artifacts="$task_root/.local/network/$CC_LOCAL_JOB"
mkdir -p "$task_artifacts"
python3 scripts/render-local.py > "$task_artifacts/model.json"
python3 - "$task_artifacts" <<'PY'
import json,os,sys
from pathlib import Path
d=Path(sys.argv[1]); items=json.loads((d/'model.json').read_text())['items']; job=items[-1]
name=os.environ['CC_LOCAL_JOB']; spec=job['spec']['template']['spec']; spec['subdomain']=name
c=spec['containers'][0]; c['command']=['python3','-m','cc_contract.network_probe']; c['args']=[]
c['env']=[{'name':'CC_JOB_NAME','value':name},{'name':'CC_SERVICE_NAME','value':name},{'name':'CC_NODE_NAME','valueFrom':{'fieldRef':{'fieldPath':'spec.nodeName'}}}]
service={'apiVersion':'v1','kind':'Service','metadata':{'name':name,'namespace':'cc-contract'},'spec':{'clusterIP':'None','publishNotReadyAddresses':True,'selector':{'app':name},'ports':[{'port':8080,'targetPort':8080}]}}
(d/'manifests.json').write_text(json.dumps({'apiVersion':'v1','kind':'List','items':[service,job]},indent=2)+'\n')
PY
kind load docker-image "$CC_LOCAL_IMAGE" --name cc-contract
kubectl --context kind-cc-contract apply --dry-run=server -f "$task_artifacts/manifests.json" > "$task_artifacts/dry-run.log"
kubectl --context kind-cc-contract apply -f "$task_artifacts/manifests.json" > "$task_artifacts/apply.log"
kubectl --context kind-cc-contract wait --for=condition=complete "job/$CC_LOCAL_JOB" -n cc-contract --timeout=90s
kubectl --context kind-cc-contract get pods -n cc-contract -l "job-name=$CC_LOCAL_JOB" -o json > "$task_artifacts/pods.json"
for task_pod in $(kubectl --context kind-cc-contract get pods -n cc-contract -l "job-name=$CC_LOCAL_JOB" -o jsonpath='{.items[*].metadata.name}'); do
  kubectl --context kind-cc-contract logs -n cc-contract "$task_pod" > "$task_artifacts/$task_pod.json"
done
python3 - "$task_artifacts" <<'PY'
import hashlib,json,sys
from pathlib import Path
d=Path(sys.argv[1]); pods=json.loads((d/'pods.json').read_text())['items']; assert len(pods)==2
assert len({p['spec']['nodeName'] for p in pods})==2
records=[json.loads((d/(p['metadata']['name']+'.json')).read_text()) for p in pods]
assert {r['index'] for r in records}=={0,1}
assert all(r['verdict']=='PASS' and not r['gpu_executed'] for r in records)
result={'verified':True,'records':records,'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in d.iterdir() if p.is_file()}}
(d/'verified.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result,indent=2))
PY
