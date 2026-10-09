"""Run the new downloader on two Kind CPU workers using one real 663-byte blob."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import hashlib

ROOT=Path(__file__).resolve().parents[1]
STATE=Path.home()/'.local/state/cc-contract/artifact-store'
os.umask(0o077)
spec=importlib.util.spec_from_file_location('artifacts',ROOT/'scripts/azure-artifacts.py')
artifacts=importlib.util.module_from_spec(spec);spec.loader.exec_module(artifacts)
token=artifacts.storage_token()
receipt=json.loads((STATE/'model-receipt.json').read_text())
file=next(r for r in receipt['files'] if Path(r['local_path']).name=='config.json')
manifest={'account':receipt['account'],'container':'models','files':[{'name':'config.json',**{k:file[k] for k in ('blob','sha256','bytes')}}]}
image=(ROOT/'.local/images/name').read_text().strip()
image_id=(ROOT/'.local/images/id').read_text().strip()
directory=ROOT/'.local/cloud-model-kind';directory.mkdir(parents=True,exist_ok=True)
ns='cc-cloud-model-pilot'


def kubectl(*args,input=None,check=True):
    return subprocess.run(['kubectl','--kubeconfig',str(ROOT/'.local/kind.kubeconfig'),'--context','kind-cc-contract',*args],input=input,text=True,capture_output=True,check=check,timeout=240)


namespace={'apiVersion':'v1','kind':'Namespace','metadata':{'name':ns,'labels':{'pod-security.kubernetes.io/enforce':'restricted'}}}
common={'namespace':ns}
container={'name':'download','image':image,'imagePullPolicy':'Never','command':['python3','-m','cc_contract.cloud_model'],'args':['--manifest','/manifest/manifest.json','--token-file','/credential/token.json','--output','/data/model','--receipt','/data/receipt.json'],'volumeMounts':[{'name':name,'mountPath':path,'readOnly':name!='data'} for name,path in [('manifest','/manifest'),('credential','/credential'),('data','/data')]],'resources':{'requests':{'cpu':'50m','memory':'32Mi'},'limits':{'cpu':'250m','memory':'128Mi'}},'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}}}
items=[{'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':'reader',**common},'automountServiceAccountToken':False},
       {'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'manifest',**common},'data':{'manifest.json':json.dumps(manifest)}},
       {'apiVersion':'v1','kind':'Secret','metadata':{'name':'credential',**common},'type':'Opaque','data':{'token.json':base64.b64encode(json.dumps({'accessToken':token}).encode()).decode()}},
       {'apiVersion':'batch/v1','kind':'Job','metadata':{'name':'cloud-byte-check',**common},'spec':{'completions':2,'parallelism':2,'completionMode':'Indexed','backoffLimit':0,'activeDeadlineSeconds':180,'template':{'metadata':{'labels':{'app':'cloud-byte-check'}},'spec':{'restartPolicy':'Never','serviceAccountName':'reader','automountServiceAccountToken':False,'nodeSelector':{'cc-contract/role':'cpu-worker'},'securityContext':{'runAsNonRoot':True,'runAsUser':10001,'runAsGroup':10001,'fsGroup':10001,'seccompProfile':{'type':'RuntimeDefault'}},'topologySpreadConstraints':[{'maxSkew':1,'topologyKey':'kubernetes.io/hostname','whenUnsatisfiable':'DoNotSchedule','labelSelector':{'matchLabels':{'app':'cloud-byte-check'}}}],'containers':[container],'volumes':[{'name':'manifest','configMap':{'name':'manifest'}},{'name':'credential','secret':{'secretName':'credential','defaultMode':288}},{'name':'data','emptyDir':{'medium':'Memory','sizeLimit':'8Mi'}}]}}}}]
try:
    kubectl('apply','--dry-run=server','-f','-',input=json.dumps(namespace))
    kubectl('apply','-f','-',input=json.dumps(namespace))
    body=json.dumps({'apiVersion':'v1','kind':'List','items':items})
    kubectl('apply','--dry-run=server','-f','-',input=body)
    kubectl('apply','-f','-',input=body)
    denied=kubectl('auth','can-i','get','secrets','--as=system:serviceaccount:'+ns+':reader','-n',ns,check=False)
    if denied.returncode!=1 or denied.stdout.strip()!='no':raise RuntimeError('Kind reader unexpectedly has API secret access')
    waited=kubectl('wait','--for=condition=complete','job/cloud-byte-check','-n',ns,'--timeout=180s',check=False)
    (directory/'wait.log').write_text(waited.stdout+waited.stderr)
    pods=json.loads(kubectl('get','pods','-n',ns,'-o','json').stdout)
    (directory/'pods.json').write_text(json.dumps(pods,indent=2))
    workers=set()
    for pod in pods['items']:
        log=kubectl('logs',pod['metadata']['name'],'-n',ns,check=False)
        (directory/(pod['metadata']['name']+'.jsonl')).write_text(log.stdout+log.stderr)
        rows=[json.loads(line) for line in log.stdout.splitlines()]
        if len(rows)!=1 or rows[0]['sha256']!=file['sha256'] or rows[0]['bytes']!=file['bytes'] or rows[0]['verified'] is not True:
            raise RuntimeError('Kind cloud byte verification failed')
        workers.add(pod['spec']['nodeName'])
    if waited.returncode!=0 or len(workers)!=2:raise RuntimeError('Both Kind workers must pass the cloud transfer check')
    result={'scope':'CPU_KIND_REAL_AZURE_BLOB_READ_NOT_GPU_OR_IMDS_VALIDATION','verified':True,'workers':sorted(workers),'image_id':image_id,'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'downloader_sha256':hashlib.sha256((ROOT/'src/cc_contract/cloud_model.py').read_bytes()).hexdigest(),'file_sha256':file['sha256'],'bytes_per_worker':file['bytes'],'secret_API_access':'DENIED','guest_managed_identity_verified':False}
    (directory/'verified.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
finally:
    kubectl('delete','namespace',ns,'--wait=true',check=False)
