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
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def command(args, **kwargs):
    return subprocess.run(args,check=True,capture_output=True,**kwargs)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False,mode=0o700)
    os.umask(0o077)
    started_ns=time.monotonic_ns()
    started_utc=datetime.now(timezone.utc).isoformat()
    os.environ['KUBECONFIG']=str(ROOT/'.local/kind.kubeconfig')
    loader=importlib.util.spec_from_file_location('sample',ROOT/'scripts/run-work-sample.py')
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
            if not candidates:raise ValueError('Imported Kind immutable image digest missing')
            # Alias names can differ, but all selected entries resolve to the
            # exact qualified content digest. Keep the bytes unchanged.
            command(['docker','exec',node,'ctr','-n','k8s.io','images','tag',sorted(candidates)[0],image])
    os.environ['CC_IMAGE_DIGEST']=image
    spec=sample.make_spec('native-reference',selected_case_target=4,safety_timeout_seconds=120,source_commit=sample.SOURCE_COMMIT)
    spec_bytes=(json.dumps(spec,indent=2)+'\n').encode();spec_hash=hashlib.sha256(spec_bytes).hexdigest()
    (args.output/'spec.json').write_bytes(spec_bytes)
    namespace='cc-work-local-'+uuid4().hex[:8]
    common={'namespace':namespace}
    documents=[{'apiVersion':'v1','kind':'Namespace','metadata':{'name':namespace}},
        {'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':'runner',**common},'automountServiceAccountToken':False},
        {'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'sample-inputs',**common},
         'data':{'run-work-sample.py':(ROOT/'scripts/run-work-sample.py').read_text(),'spec.json':spec_bytes.decode()}}]
    manifest={'apiVersion':'v1','kind':'List','items':documents}
    command(['kubectl','apply','-f','-'],input=json.dumps(manifest).encode())
    receipts=[]
    try:
        # Separate jobs run one after another; even CPU qualification does not
        # rely on concurrent execution to establish correct sample ordering.
        for index,node in enumerate(('cc-contract-worker','cc-contract-worker2')):
            runner="""import base64,io,subprocess,tarfile,sys
with open('/evidence/harness.stdout','wb') as stdout,open('/evidence/harness.stderr','wb') as stderr:
    result=subprocess.run(sys.argv[1:],stdout=stdout,stderr=stderr)
data=io.BytesIO()
with tarfile.open(fileobj=data,mode='w:gz',compresslevel=1) as archive:
    archive.add('/evidence',arcname='evidence')
print(base64.b64encode(data.getvalue()).decode())
sys.exit(result.returncode)
"""
            container={'name':'sample','image':image,'imagePullPolicy':'Never',
                'command':['python3','-c',runner,'python3','/inputs/run-work-sample.py',
                    '--spec','/inputs/spec.json','--spec-sha256',spec_hash,'--output','/evidence/runs',
                    '--backend','native-reference','--selected-case-target','4','--safety-timeout-seconds','120'],
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
                            {'name':'evidence','emptyDir':{'sizeLimit':'512Mi'}}]}}}}
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
            (args.output/('pod-'+str(index)+'.stdout')).write_bytes(logs)
            (args.output/('pod-'+str(index)+'.stderr')).write_bytes(log_result.stderr)
            # The wrapper exports partial originals even when the harness
            # exits nonzero; preserve these before interpreting success.
            raw=base64.b64decode(logs.strip(),validate=True) if logs.strip() else b''
            archive_path=args.output/('worker-'+str(index)+'.tar.gz')
            if raw:archive_path.write_bytes(raw)
            if pods['items'][0]['status']['phase']!='Succeeded':
                events=command(['kubectl','get','events','-n',namespace,'-o','json']).stdout
                (args.output/('failure-'+str(index)+'.log')).write_bytes(logs+log_result.stderr+events)
                raise RuntimeError('Kind sequential CPU sample failed; preserved original logs')
            with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
                members=archive.getmembers()
                names=set()
                for member in members:
                    path=Path(member.name)
                    if (member.name in names or path.is_absolute() or '..' in path.parts or
                            not (member.isfile() or member.isdir()) or
                            path.parts[0]!='evidence'):
                        raise ValueError('Unsafe or duplicate Kind original archive entry')
                    names.add(member.name)
                prefix='evidence/runs/'
                receipt=json.loads(archive.extractfile(prefix+'receipt.json').read())
                if (receipt['state']!='COMPLETE_FINITE_WORK_SAMPLE' or receipt['gpu_executed'] is not False or
                        len(receipt['jobs'])!=14 or receipt['spec_sha256']!=spec_hash or
                        receipt['harness_sha256']!=sample.harness_sha256() or
                        receipt['source_commit']!=sample.SOURCE_COMMIT or
                        receipt['finite_work_completed_jobs']!=14 or
                        [j['configuration'] for j in receipt['jobs']]!=spec['schedule']):
                    raise ValueError('Kind receipt scope, completion or specification mismatch')
                if any(job['state']!='COMPLETE_CASE_LIMIT_LOCAL_ONLY' or not job['development_finite_work_completion'] or job['diagnostics']['completed_cases']!=4 for job in receipt['jobs']):
                    raise ValueError('Incomplete CPU sample campaign')
                for left,right in zip(receipt['jobs'],receipt['jobs'][1:]):
                    if left['finished_monotonic_ns']>right['started_monotonic_ns']:
                        raise ValueError('CPU sample job intervals overlap')
                for job in receipt['jobs']:
                    data=archive.extractfile(prefix+job['raw_file']).read()
                    if hashlib.sha256(data).hexdigest()!=job['raw_sha256']:
                        raise ValueError('Kind original trace integrity changed')
                    for artifact in job['artifacts']:
                        payload=archive.extractfile(prefix+artifact['file']).read()
                        if len(payload)!=artifact['bytes'] or hashlib.sha256(payload).hexdigest()!=artifact['sha256']:
                            raise ValueError('Kind original artifact integrity changed')
                archive_spec=archive.extractfile(prefix+'spec.json').read()
                if archive_spec!=spec_bytes:raise ValueError('Kind original specification changed')
                journal=archive.extractfile(prefix+'journal.jsonl').read()
                if hashlib.sha256(journal).hexdigest()!=receipt['journal_sha256']:
                    raise ValueError('Kind original journal integrity changed')
            receipts.append({'node':node,'archive_sha256':hashlib.sha256(raw).hexdigest(),
                             'archive_bytes':len(raw),'completed_jobs':14,'gpu_executed':False,
                             'finite_work_completed_jobs':14,'selected_cases_per_job':4,
                             'first_job_started_monotonic_ns':receipt['jobs'][0]['started_monotonic_ns'],
                             'last_job_finished_monotonic_ns':receipt['jobs'][-1]['finished_monotonic_ns'],
                             'actual_total_seconds':receipt['actual_total_seconds']})
        if receipts[0]['last_job_finished_monotonic_ns']>receipts[1]['first_job_started_monotonic_ns']:
            raise ValueError('CPU worker sample execution intervals overlap')
        denied=subprocess.run(
            ['kubectl','auth','can-i','get','secrets','-n',namespace,'--as=system:serviceaccount:'+namespace+':runner'],capture_output=True)
        if denied.stdout.strip()!=b'no':raise ValueError('Sample service account can read secrets')
        result={'scope':'CPU_KIND_FINITE_WORK_FUNCTIONAL_PIPELINE_ONLY','verified':True,'gpu_executed':False,
                'image_digest':image,'image_id':inspection['Id'],'science_source_commit':sample.SOURCE_COMMIT,
                'harness_sha256':sample.harness_sha256(),'spec_sha256':spec_hash,
                'started_utc':started_utc,'actual_qualification_seconds_before_cleanup':(time.monotonic_ns()-started_ns)/1e9,
                'jobs_per_worker':14,'selected_cases_per_job':4,'safety_timeout_seconds':120,'workers':receipts,'secret_access':'DENIED','new_images_built':0}
        (args.output/'verified.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    finally:
        command(['kubectl','delete','namespace',namespace,'--wait=true','--timeout=90s'])
        (args.output/'cleanup.json').write_text(json.dumps({'namespace_deleted':namespace,
            'finished_utc':datetime.now(timezone.utc).isoformat(),
            'total_seconds':(time.monotonic_ns()-started_ns)/1e9})+'\n')


if __name__=='__main__':main()
