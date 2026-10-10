"""Qualify locally built HDSC images on restricted Kind CPU pods, never cloud."""
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
    return subprocess.run(args, check=True, capture_output=True, timeout=600, **kwargs)


CORE = '''import json,subprocess,sys
from cc_contract.hdsc_dynamic import run
from cc_contract.hdsc_rq2 import execute
from cc_contract.hdsc_benchmark import schedule
rows=[execute(r,'cpu-model',None) for r in schedule('development') if r['tool']=='direct']
assert len(rows)==48 and sum(r['activated'] for r in rows)==24
assert all(r['B0_cuda_status']=='UNSUPPORTED' for r in rows)
dynamic=[run(82000,fault) for fault in (None,'L1','L2','C1','C2')]
for r in dynamic:assert sum(s['verdict']['classification']!='PASS' for s in r['steps'])==int(r['fault'] is not None)
p=subprocess.run(['/usr/local/bin/cc-hdsc-dynamic-worker'],capture_output=True,timeout=20)
assert p.returncode==0 and json.loads(p.stdout)['execution_status']=='UNSUPPORTED'
version=subprocess.check_output(['compute-sanitizer','--version']).decode()
print(json.dumps({'scope':'CPU_ONLY','runs':48,'dynamic_sequences':5,'cuda':'UNSUPPORTED','sanitizer_version':version}))
'''
AI = '''import json,pathlib,time
from cc_contract.hdsc_ai import Transformer
from cc_contract.hdsc_graph_attention import equivalence
path=pathlib.Path('/tmp/model')
deadline=time.monotonic()+180
while not (path/'READY').exists():
 if time.monotonic()>deadline:raise RuntimeError('model copy deadline')
 time.sleep(.2)
model=Transformer(path,'cpu')
equivalences=[equivalence(model,seed) for seed in range(82000,82004)]
for fault in ('L1','L2','C1','C2'):
 for active in (False,True):
  r=model.request(82000,fault,inject=active,capture_logits=False)
  assert sum(x['verdict']['classification']!='PASS' for x in r['steps'])==int(active)
assert not model.torch.cuda.is_available()
print(json.dumps({'scope':'CPU_ONLY','AI_pairs':4,'trained_model':True,'cuda':'UNSUPPORTED','torch':model.torch.__version__,
                  'upstream_exact_logits':all(r['exact_logits_equal'] for r in equivalences),'equivalence_prompts':4,
                  'graph_attention_adapter':model.graph_attention_adapter}))
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model',type=Path);p.add_argument('--nodes',default='cc-contract-worker,cc-contract-worker2')
    p.add_argument('--stream-load',action='store_true',help='Avoid an additional large image archive on the PC')
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False,mode=0o700)
    os.environ['KUBECONFIG']=str(ROOT/'.local/kind.kubeconfig')
    inspection=json.loads(command(['docker','image','inspect',args.image]).stdout)[0]
    (args.output/'image-inspect.json').write_text(json.dumps(inspection,indent=2)+'\n')
    namespace='cc-hdsc-'+uuid4().hex[:8];receipts=[]
    doc={'apiVersion':'v1','kind':'Namespace','metadata':{'name':namespace,'labels':{'pod-security.kubernetes.io/enforce':'restricted'}}}
    command(['kubectl','apply','-f','-'],input=json.dumps(doc).encode())
    try:
        sa={'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':'runner','namespace':namespace},'automountServiceAccountToken':False}
        command(['kubectl','apply','-f','-'],input=json.dumps(sa).encode())
        denied=subprocess.run(['kubectl','auth','can-i','get','secrets','-n',namespace,'--as',f'system:serviceaccount:{namespace}:runner'],capture_output=True,timeout=30)
        assert denied.returncode==1 and denied.stdout.strip()==b'no'
        for index,node in enumerate(args.nodes.split(',')):
            if args.stream_load:
                with (args.output/f'import-{index}.log').open('wb') as log:
                    exporter=subprocess.Popen(['docker','image','save',args.image],stdout=subprocess.PIPE,stderr=log)
                    try:
                        subprocess.run(['docker','exec','-i',node,'ctr','--namespace','k8s.io','images','import',
                                        '--platform','linux/amd64','--snapshotter','overlayfs','-'],
                                       stdin=exporter.stdout,stdout=log,stderr=log,check=True,timeout=600)
                        exporter.stdout.close()
                        if exporter.wait(timeout=30):raise RuntimeError('Image export failed')
                    finally:
                        if exporter.poll() is None:exporter.kill();exporter.wait()
            else:command(['kind','load','docker-image',args.image,'--name','cc-contract','--nodes',node])
            name='check-'+str(index)
            pod={'apiVersion':'v1','kind':'Pod','metadata':{'name':name,'namespace':namespace},'spec':{
                'restartPolicy':'Never','activeDeadlineSeconds':300,'serviceAccountName':'runner','automountServiceAccountToken':False,
                'nodeSelector':{'kubernetes.io/hostname':node},
                'securityContext':{'runAsNonRoot':True,'runAsUser':10001,'runAsGroup':10001,'fsGroup':10001,'seccompProfile':{'type':'RuntimeDefault'}},
                'containers':[{'name':'test','image':args.image,'imagePullPolicy':'Never','command':['python','-c',AI if args.model else CORE],
                    'resources':{'requests':{'cpu':'100m','memory':'128Mi'},'limits':{'cpu':'2','memory':'2Gi'}},
                    'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},
                    'volumeMounts':[{'name':'tmp','mountPath':'/tmp'}]}],
                'volumes':[{'name':'tmp','emptyDir':{'sizeLimit':'256Mi'}}]}}
            command(['kubectl','apply','--dry-run=server','-f','-'],input=json.dumps(pod).encode())
            command(['kubectl','apply','-f','-'],input=json.dumps(pod).encode())
            if args.model:
                command(['kubectl','wait','--for=condition=Ready',f'pod/{name}','-n',namespace,'--timeout=90s'])
                command(['kubectl','cp',str(args.model),f'{namespace}/{name}:/tmp/model','-c','test'])
                command(['kubectl','exec','-n',namespace,name,'--','touch','/tmp/model/READY'])
            deadline=time.monotonic()+300
            while True:
                state=json.loads(command(['kubectl','get','pod',name,'-n',namespace,'-o','json']).stdout)
                if state['status']['phase'] in ('Succeeded','Failed') or time.monotonic()>deadline:break
                time.sleep(1)
            log=command(['kubectl','logs',name,'-n',namespace]).stdout
            (args.output/f'pod-{index}.json').write_text(json.dumps(state,indent=2)+'\n')
            (args.output/f'log-{index}.txt').write_bytes(log)
            if state['status']['phase']!='Succeeded':raise ValueError('Kind qualification failed; original log retained')
            result=json.loads(log.splitlines()[-1]);assert result['scope']=='CPU_ONLY' and result['cuda']=='UNSUPPORTED'
            receipts.append({'node':node,'log_sha256':hashlib.sha256(log).hexdigest(),'image_id':state['status']['containerStatuses'][0]['imageID'],'result':result})
            print(node+': CPU qualification passed',flush=True)
            command(['kubectl','delete','pod',name,'-n',namespace,'--wait=true'])
        receipt={'state':'PASS_KIND_CPU_ONLY','utc':datetime.now(timezone.utc).isoformat(),'image':args.image,
                 'local_image_id':inspection['Id'],'receipts':receipts,'rbac_secrets_denied':True,'GPU_executed':False}
        (args.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    finally:command(['kubectl','delete','namespace',namespace,'--wait=true','--timeout=90s'])


if __name__=='__main__':main()
