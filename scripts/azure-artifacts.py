"""Dedicated private project storage; verify remote bytes before releasing caches."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
STATE=Path.home()/'.local/state/cc-contract/artifact-store'
MODULE=ROOT/'infrastructure/azure/artifact-store'
os.umask(0o077)
STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
TOKEN_LOCK=threading.Lock()
BLOCK_SIZE=32*2**20


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
        separator=chr(92)
        return separator*2+'wsl.localhost'+separator+os.environ.get('WSL_DISTRO_NAME','Ubuntu-22.04')+str(Path(path).resolve()).replace('/',separator)
    return str(Path(path).resolve())


def storage_token():
    with TOKEN_LOCK:
        path=STATE/'storage-token.json'
        data=json.loads(path.read_text()) if path.exists() else {}
        token=data.get('accessToken','')
        expiry=json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'==')).get('exp',0) if token else 0
        if expiry<time.time()+300:
            subprocess.run([sys.executable,str(ROOT/'scripts/azure-storage-login.py'),'--silent'],check=True,timeout=120,capture_output=True)
            token=json.loads(path.read_text())['accessToken']
        return token


def request(account,container,blob,method='GET',data=None,query=None,headers=None):
    url=f'https://{account}.blob.core.windows.net/{container}/'+urllib.parse.quote(blob,safe='/')
    if query:url+='?'+urllib.parse.urlencode(query)
    req=urllib.request.Request(url,data=data,method=method,
          headers={'Authorization':'Bearer '+storage_token(),'x-ms-version':'2023-11-03',**(headers or {})})
    for attempt in range(3):
        try:return urllib.request.urlopen(req,timeout=180)
        except urllib.error.HTTPError as error:
            if error.code not in (408,429,500,502,503,504) or attempt==2:raise
        except (urllib.error.URLError,TimeoutError):
            if attempt==2:raise
        time.sleep(2**attempt)


def blob_exists(account,container,blob):
    try:
        with request(account,container,blob,method='HEAD'):return True
    except urllib.error.HTTPError as error:
        if error.code==404:return False
        raise


def upload_blocks(account,container,blob,file,digest):
    block_size=BLOCK_SIZE;size=file.stat().st_size
    if size==0:
        with request(account,container,blob,method='PUT',data=b'',headers={
                'x-ms-blob-type':'BlockBlob','x-ms-meta-sha256':digest,'If-None-Match':'*'}):pass
        return
    count=(size+block_size-1)//block_size
    def block(index):
        block_id=base64.b64encode(f'{index:08d}'.encode()).decode()
        with file.open('rb') as source:source.seek(index*block_size);data=source.read(block_size)
        checksum=base64.b64encode(hashlib.md5(data).digest()).decode()
        with request(account,container,blob,method='PUT',data=data,query={'comp':'block','blockid':block_id},headers={'Content-MD5':checksum}):pass
        return block_id
    blocks=[]
    with ThreadPoolExecutor(max_workers=4) as workers:
        for index,block_id in enumerate(workers.map(block,range(count))):
            blocks.append(block_id)
            if (index+1)%16==0 or index+1==count:print('Transferred:',file.name,min((index+1)*block_size,size),'/',size,'bytes',flush=True)
    body=('<BlockList>'+''.join('<Latest>'+value+'</Latest>' for value in blocks)+'</BlockList>').encode()
    with request(account,container,blob,method='PUT',data=body,query={'comp':'blocklist'},headers={'Content-Type':'application/xml','x-ms-meta-sha256':digest,'If-None-Match':'*'}):pass


def remote_hash(account,container,blob):
    value=hashlib.sha256();size=0
    with request(account,container,blob) as response:
        for part in iter(lambda:response.read(8*2**20),b''):value.update(part);size+=len(part)
    return value.hexdigest(),size


def upload(files,container,receipt_name,expected_hashes=None):
    account=json.loads((STATE/'outputs.json').read_text())['account_name']['value']
    path=STATE/receipt_name;receipt=json.loads(path.read_text()) if path.exists() else {'files':[],'container':container,'account':account}
    known={f['local_path']:f for f in receipt['files']}
    for file in files:
        file=Path(file)
        if file.is_symlink() or not file.is_file():raise ValueError('Only regular project files may be uploaded')
        file=file.resolve()
        digest=sha(file);blob=digest+'/'+file.name
        if expected_hashes is not None and digest!=expected_hashes.get(file.name):raise ValueError('Prepared model source changed')
        if str(file) in known and known[str(file)]['sha256']==digest and known[str(file)].get('remote_bytes_verified') is True:
            continue
        exists=blob_exists(account,container,blob)
        if not exists:
            print('Uploading:',file.name,'bytes:',file.stat().st_size,flush=True)
            upload_blocks(account,container,blob,file,digest)
        print('Uploaded; verifying complete remote bytes:',file.name,flush=True)
        remote,size=remote_hash(account,container,blob)
        if remote!=digest or size!=file.stat().st_size:raise RuntimeError('Remote byte verification failed; local source retained')
        record={'local_path':str(file),'blob':blob,'sha256':digest,'bytes':size,'remote_bytes_verified':True,
                'timestamp_utc':datetime.now(timezone.utc).isoformat()}
        receipt['files']=[r for r in receipt['files'] if r['local_path']!=str(file)]+[record];atomic(path,receipt)
        print('Verified remote SHA-256:',file.name,flush=True)
    return receipt


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['deploy','model','evidence','release-model'])
    parser.add_argument('--model-directory',type=Path,default=Path.home()/'.local/state/cc-contract/models/qwen2.5-7b')
    args=parser.parse_args()
    if args.action=='deploy':deploy();return
    if args.action=='model':
        manifest=args.model_directory/'cc-model-manifest.json';data=json.loads(manifest.read_text())
        names=sorted(data['file_sha256'])
        if any(Path(name).name!=name or name in ('.','..') for name in names):raise ValueError('Model manifest must contain basenames only')
        files=[args.model_directory/name for name in names]
        for file in files:
            if file.is_symlink() or not file.is_file():raise ValueError('Prepared model source is missing or not a regular file')
        files.extend([manifest,ROOT/'experiments/inference-corpus.json'])
        expected={**data['file_sha256'],manifest.name:sha(manifest),'inference-corpus.json':sha(ROOT/'experiments/inference-corpus.json')}
        receipt=upload(files,'models','model-receipt.json',expected_hashes=expected)
        print(json.dumps({'verified_files':len(receipt['files']),'bytes':sum(f['bytes'] for f in receipt['files'])}))
    elif args.action=='evidence':
        files=[]
        for name in ('ir','torch'):
            files.extend(p for p in (ROOT/'.local'/name).rglob('*') if p.is_file())
        for name in ('cpu-pipeline','cpu-pipeline-analysis'):
            files.extend(p for p in (Path.home()/'.local/state/cc-contract'/name).rglob('*') if p.is_file())
        files.extend((Path.home()/'.local/state/cc-contract/e0-20261009b').glob('guest-evidence-*.tar.gz'))
        archive=STATE/'qualified-evidence.tar';manifest=STATE/'evidence-files.json'
        sources=[]
        for file in sorted(set(files)):
            if file.is_symlink():raise ValueError('Evidence symlinks must be reviewed separately')
            prefix='repo-local/' if file.is_relative_to(ROOT/'.local') else 'private-evidence/'
            base=ROOT/'.local' if file.is_relative_to(ROOT/'.local') else Path.home()/'.local/state/cc-contract'
            sources.append({'source':str(file),'name':prefix+str(file.relative_to(base)),'sha256':sha(file),'bytes':file.stat().st_size})
        atomic(manifest,{'files':sources})
        temporary=STATE/'qualified-evidence.tar.tmp'
        with tarfile.open(temporary,'w') as output:
            for record in sources:
                file=Path(record['source']);info=output.gettarinfo(str(file),arcname=record['name'])
                info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0;info.mode=0o400
                with file.open('rb') as data:output.addfile(info,data)
        with tarfile.open(temporary,'r') as check:
            for record in sources:
                data=check.extractfile(record['name']);digest=hashlib.sha256()
                for part in iter(lambda:data.read(8*2**20),b''):digest.update(part)
                if digest.hexdigest()!=record['sha256']:raise ValueError('Evidence snapshot changed')
        temporary.replace(archive)
        receipt=upload([archive,manifest],'evidence','evidence-receipt.json')
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
