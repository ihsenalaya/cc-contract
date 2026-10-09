"""Qualify the mounted sample harness sequentially on two existing Kind CPU nodes.

No image build, GPU access, model download or CUDA/CC validation is involved.
Original CPU traces are exported before deleting this dedicated namespace.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import io
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def command(args, **kwargs):
    return subprocess.run(args,check=True,capture_output=True,**kwargs)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False,mode=0o700)
    os.environ['KUBECONFIG']=str(ROOT/'.local/kind.kubeconfig')
    loader=importlib.util.spec_from_file_location('sample',ROOT/'scripts/run-sequential-sample.py')
    sample=importlib.util.module_from_spec(loader);loader.loader.exec_module(sample)
    image=sample.IMAGE_DIGEST
    inspection=json.loads(command(['docker','image','inspect',image]).stdout)[0]
    gate=json.loads((ROOT/'.local/ir/kind-verified.json').read_text())
    if not gate['verified'] or gate['image_id']!=inspection['Id'] or inspection['Config']['Labels']['org.opencontainers.image.revision']!=sample.SOURCE_COMMIT:
        raise ValueError('Existing IR image lacks matching local/Kind source qualification')
    (args.output/'image-inspect.json').write_text(json.dumps(inspection,indent=2)+'\n')
    command(['kind','load','docker-image',image,'--name','cc-contract',
             '--nodes','cc-contract-worker,cc-contract-worker2'])
    # Docker's OCI export can import digest-only images under an import-* name.
    # Restore the immutable registry name without changing the image content.
    for node in ('cc-contract-worker','cc-contract-worker2'):
        imported=command(['docker','exec',node,'ctr','-n','k8s.io','images','ls','-q']).stdout.decode().splitlines()
        for ref in imported:
            if ref.startswith('import-') and ref.endswith('@'+image.split('@')[1]):
                normalized='docker.io/library/'+ref
                if normalized not in imported:
                    command(['docker','exec',node,'ctr','-n','k8s.io','images','tag',ref,normalized])
        if image not in imported:
            candidates=[ref for ref in imported if ref.endswith('@'+image.split('@')[1])]
            if len(candidates)!=1:raise ValueError('Imported Kind image digest is not unique')
            command(['docker','exec',node,'ctr','-n','k8s.io','images','tag',candidates[0],image])
    os.environ['CC_IMAGE_DIGEST']=image
    spec=sample.make_spec('native-reference',budget_seconds=0.1,source_commit=sample.SOURCE_COMMIT)
    spec_bytes=(json.dumps(spec,indent=2)+'\n').encode();spec_hash=hashlib.sha256(spec_bytes).hexdigest()
    (args.output/'spec.json').write_bytes(spec_bytes)
    namespace='cc-sample-local-'+uuid4().hex[:8]
    common={'namespace':namespace}
    documents=[{'apiVersion':'v1','kind':'Namespace','metadata':{'name':namespace}},
        {'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':'runner',**common},'automountServiceAccountToken':False},
        {'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'sample-inputs',**common},
         'data':{'run-sequential-sample.py':(ROOT/'scripts/run-sequential-sample.py').read_text(),'spec.json':spec_bytes.decode()}}]
    manifest={'apiVersion':'v1','kind':'List','items':documents}
    command(['kubectl','apply','-f','-'],input=json.dumps(manifest).encode())
    receipts=[]
    try:
        # Separate jobs run one after another; even CPU qualification does not
        # rely on concurrent execution to establish correct sample ordering.
        for index,node in enumerate(('cc-contract-worker','cc-contract-worker2')):
            runner="""import base64,io,subprocess,tarfile,sys
subprocess.run(sys.argv[1:],check=True,stdout=subprocess.DEVNULL)
data=io.BytesIO()
with tarfile.open(fileobj=data,mode='w:gz',compresslevel=1) as archive:
    archive.add('/evidence/runs',arcname='runs')
print(base64.b64encode(data.getvalue()).decode())
"""
            container={'name':'sample','image':image,'imagePullPolicy':'Never',
                'command':['python3','-c',runner,'python3','/inputs/run-sequential-sample.py',
                    '--spec','/inputs/spec.json','--spec-sha256',spec_hash,'--output','/evidence/runs',
                    '--backend','native-reference','--budget-seconds','0.1'],
                'env':[{'name':'CC_IMAGE_DIGEST','value':image}],
                'resources':{'requests':{'cpu':'100m','memory':'128Mi'},'limits':{'cpu':'2','memory':'1Gi'}},
                'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},
                'volumeMounts':[{'name':'inputs','mountPath':'/inputs','readOnly':True},{'name':'evidence','mountPath':'/evidence'}]}
            job={'apiVersion':'batch/v1','kind':'Job','metadata':{'name':'sample-'+str(index),**common},
                'spec':{'backoffLimit':0,'activeDeadlineSeconds':180,'parallelism':1,'completions':1,
                    'template':{'spec':{'restartPolicy':'Never','serviceAccountName':'runner','automountServiceAccountToken':False,
                        'nodeSelector':{'kubernetes.io/hostname':node},
                        'securityContext':{'runAsNonRoot':True,'runAsUser':10001,'runAsGroup':10001,'fsGroup':10001,'seccompProfile':{'type':'RuntimeDefault'}},
                        'containers':[container],'volumes':[{'name':'inputs','configMap':{'name':'sample-inputs'}},
                            {'name':'evidence','emptyDir':{'sizeLimit':'128Mi'}}]}}}}
            command(['kubectl','apply','--dry-run=server','-f','-'],input=json.dumps(job).encode())
            command(['kubectl','apply','-f','-'],input=json.dumps(job).encode())
            deadline=time.monotonic()+180
            while True:
                pods=json.loads(command(['kubectl','get','pods','-n',namespace,'-l','job-name=sample-'+str(index),'-o','json']).stdout)
                if pods['items']:
                    status=pods['items'][0]['status']
                    reasons=[s.get('state',{}).get('waiting',{}).get('reason') for s in status.get('containerStatuses',[])]
                    if status['phase'] in ('Succeeded','Failed') or any(r in ('ErrImageNeverPull','CreateContainerError','CreateContainerConfigError','ImagePullBackOff') for r in reasons):break
                if time.monotonic()>=deadline:break
                time.sleep(1)
            (args.output/('pods-'+str(index)+'.json')).write_text(json.dumps(pods,indent=2)+'\n')
            pod=pods['items'][0]['metadata']['name']
            log_result=subprocess.run(['kubectl','logs','-n',namespace,pod],capture_output=True)
            logs=log_result.stdout
            if pods['items'][0]['status']['phase']!='Succeeded':
                events=command(['kubectl','get','events','-n',namespace,'-o','json']).stdout
                (args.output/('failure-'+str(index)+'.log')).write_bytes(logs+log_result.stderr+events)
                raise RuntimeError('Kind sequential CPU sample failed; preserved original logs')
            raw=base64.b64decode(logs.strip(),validate=True)
            archive_path=args.output/('worker-'+str(index)+'.tar.gz');archive_path.write_bytes(raw)
            with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
                receipt=json.loads(archive.extractfile('runs/receipt.json').read())
                if receipt['state']!='COMPLETE_SAMPLE' or receipt['gpu_executed'] is not False or len(receipt['jobs'])!=14 or receipt['spec_sha256']!=spec_hash:
                    raise ValueError('Kind receipt scope, completion or specification mismatch')
                if any(job['state']!='COMPLETE_BUDGET' for job in receipt['jobs']):
                    raise ValueError('Incomplete CPU sample campaign')
                for left,right in zip(receipt['jobs'],receipt['jobs'][1:]):
                    if left['finished_monotonic_ns']>right['started_monotonic_ns']:
                        raise ValueError('CPU sample job intervals overlap')
                for job in receipt['jobs']:
                    data=archive.extractfile('runs/'+job['raw_file']).read()
                    if hashlib.sha256(data).hexdigest()!=job['raw_sha256']:
                        raise ValueError('Kind original trace integrity changed')
            receipts.append({'node':node,'archive_sha256':hashlib.sha256(raw).hexdigest(),
                             'archive_bytes':len(raw),'completed_jobs':14,'gpu_executed':False,
                             'actual_total_seconds':receipt['actual_total_seconds']})
        denied=subprocess.run(
            ['kubectl','auth','can-i','get','secrets','-n',namespace,'--as=system:serviceaccount:'+namespace+':runner'],capture_output=True)
        if denied.stdout.strip()!=b'no':raise ValueError('Sample service account can read secrets')
        result={'scope':'CPU_KIND_SEQUENTIAL_SAMPLE_PIPELINE_ONLY','verified':True,'gpu_executed':False,
                'image_digest':image,'image_id':inspection['Id'],'science_source_commit':sample.SOURCE_COMMIT,
                'harness_sha256':sample.harness_sha256(),'spec_sha256':spec_hash,
                'jobs_per_worker':14,'workers':receipts,'secret_access':'DENIED','new_images_built':0}
        (args.output/'verified.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    finally:
        command(['kubectl','delete','namespace',namespace,'--wait=true','--timeout=90s'])


if __name__=='__main__':main()
