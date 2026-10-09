"""Dedicated private project storage; verify remote bytes before releasing caches."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
STATE=Path.home()/'.local/state/cc-contract/artifact-store'
MODULE=ROOT/'infrastructure/azure/artifact-store'
os.umask(0o077)
STATE.mkdir(parents=True,exist_ok=True,mode=0o700)


def azure(*args,timeout=180):
    data=subprocess.check_output(['az',*args,'--only-show-errors','-o','json'],timeout=timeout)
    try:return json.loads(data.decode('utf-8-sig'))
    except UnicodeDecodeError:return json.loads(data.decode('cp1252'))


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as file:
        for part in iter(lambda:file.read(8*2**20),b''):value.update(part)
    return value.hexdigest()


def atomic(path,data):
    temporary=Path(str(path)+'.tmp');temporary.write_text(json.dumps(data,indent=2)+'\n');temporary.replace(path)


def deploy():
    inputs=STATE/'inputs.json'
    if not inputs.exists():
        account=azure('account','show');principal=azure('ad','signed-in-user','show','--query','id')
        atomic(inputs,{'subscription_id':account['id'],'principal_id':principal,'account_name':'cccontract'+uuid4().hex[:12]})
    environment={**os.environ,'TF_PLUGIN_CACHE_DIR':str(ROOT/'infrastructure/azure/gpu-window/.terraform/providers')}
    with (STATE/'deployment.log').open('a') as log:
        def tf(*args):return subprocess.run(['terraform',f'-chdir={MODULE}',*args],stdout=log,stderr=subprocess.STDOUT,env=environment,check=True)
        tf('init','-input=false','-reconfigure',f'-backend-config=path={STATE}/terraform.tfstate')
        tf('plan','-input=false',f'-var-file={inputs}',f'-out={STATE}/plan.tfplan')
        plan=json.loads(subprocess.check_output(['terraform',f'-chdir={MODULE}','show','-json',str(STATE/'plan.tfplan')]))
        changes=plan['resource_changes']
        if len(changes)!=5 or any(c['change']['actions'] not in (['create'],['no-op']) for c in changes):
            raise RuntimeError('Storage plan must contain only the five dedicated resources')
        atomic(STATE/'plan-summary.json',{'plan_sha256':sha(STATE/'plan.tfplan'),'resources':5,'gpu_resources':0,'authorization':'user requested Azure project storage and local cleanup'})
        print('Dedicated private storage plan verified: five resources, zero GPUs',flush=True)
        tf('apply','-input=false',str(STATE/'plan.tfplan'))
    outputs=json.loads(subprocess.check_output(['terraform',f'-chdir={MODULE}','output','-json']))
    atomic(STATE/'outputs.json',outputs)
    print('Private Azure storage created; no GPU provisioned',flush=True)


def windows_path(path):
    executable=shutil.which('az') or ''
    if executable.startswith('/mnt/c/'):
        return '\\\\wsl.localhost\\'+os.environ.get('WSL_DISTRO_NAME','Ubuntu-22.04')+str(Path(path).resolve()).replace('/','\\')
    return str(Path(path).resolve())


def remote_hash(account,container,blob):
    token=azure('account','get-access-token','--resource','https://storage.azure.com/','--query','accessToken')
    request=urllib.request.Request(f'https://{account}.blob.core.windows.net/{container}/{blob}',
             headers={'Authorization':'Bearer '+token,'x-ms-version':'2023-11-03'})
    value=hashlib.sha256();size=0
    with urllib.request.urlopen(request,timeout=180) as response:
        for part in iter(lambda:response.read(8*2**20),b''):value.update(part);size+=len(part)
    return value.hexdigest(),size


def upload(files,container,receipt_name):
    account=json.loads((STATE/'outputs.json').read_text())['account_name']['value']
    path=STATE/receipt_name;receipt=json.loads(path.read_text()) if path.exists() else {'files':[],'container':container,'account':account}
    known={f['local_path']:f for f in receipt['files']}
    for file in files:
        file=Path(file).resolve()
        if file.is_symlink() or not file.is_file():raise ValueError('Only regular project files may be uploaded')
        digest=sha(file);blob=digest+'/'+file.name
        if str(file) in known and known[str(file)]['sha256']==digest:
            continue
        exists=azure('storage','blob','exists','--account-name',account,'--container-name',container,'--name',blob,'--auth-mode','login')['exists']
        if not exists:
            azure('storage','blob','upload','--account-name',account,'--container-name',container,'--name',blob,
                  '--file',windows_path(file),'--auth-mode','login','--overwrite','false','--validate-content','--no-progress',
                  '--metadata','sha256='+digest,timeout=3600)
        print('Uploaded; verifying complete remote bytes:',file.name,flush=True)
        remote,size=remote_hash(account,container,blob)
        if remote!=digest or size!=file.stat().st_size:raise RuntimeError('Remote byte verification failed; local source retained')
        record={'local_path':str(file),'blob':blob,'sha256':digest,'bytes':size,'remote_bytes_verified':True,
                'timestamp_utc':datetime.now(timezone.utc).isoformat()}
        receipt['files'].append(record);atomic(path,receipt)
        print('Verified remote SHA-256:',file.name,flush=True)
    return receipt


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['deploy','model','evidence','release-model'])
    parser.add_argument('--model-directory',type=Path,default=Path.home()/'.local/state/cc-contract/models/qwen2.5-7b')
    args=parser.parse_args()
    if args.action=='deploy':deploy();return
    if args.action=='model':
        manifest=args.model_directory/'cc-model-manifest.json';data=json.loads(manifest.read_text())
        files=[args.model_directory/name for name in sorted(data['file_sha256'])]
        for file in files:
            if Path(file.name).name!=file.name or sha(file)!=data['file_sha256'][file.name]:raise ValueError('Prepared model source changed')
        files.extend([manifest,ROOT/'experiments/inference-corpus.json'])
        receipt=upload(files,'models','model-receipt.json')
        print(json.dumps({'verified_files':len(receipt['files']),'bytes':sum(f['bytes'] for f in receipt['files'])}))
    elif args.action=='evidence':
        files=[]
        for name in ('ir','torch'):
            files.extend(p for p in (ROOT/'.local'/name).rglob('*') if p.is_file())
        for name in ('cpu-pipeline','cpu-pipeline-analysis'):
            files.extend(p for p in (Path.home()/'.local/state/cc-contract'/name).rglob('*') if p.is_file())
        files.extend((Path.home()/'.local/state/cc-contract/e0-20261009b').glob('guest-evidence-*.tar.gz'))
        receipt=upload(files,'evidence','evidence-receipt.json')
        print(json.dumps({'verified_evidence_files':len(receipt['files'])}))
    else:
        receipt=json.loads((STATE/'model-receipt.json').read_text());released=[]
        for record in receipt['files']:
            file=Path(record['local_path'])
            if file.parent!=args.model_directory.resolve() or file.suffix!='.safetensors':continue
            if not record['remote_bytes_verified'] or sha(file)!=record['sha256']:raise ValueError('Source/backup verification is missing')
            file.unlink();released.append({'name':file.name,'bytes':record['bytes'],'sha256':record['sha256']})
        atomic(STATE/'released-model-cache.json',{'released':released,'remote_receipt_sha256':sha(STATE/'model-receipt.json')})
        print(json.dumps({'verified_model_cache_bytes_released':sum(f['bytes'] for f in released)}))


if __name__=='__main__':main()
