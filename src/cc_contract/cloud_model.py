"""Download hash-bound project blobs with Entra credentials; no model code execution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request


def validate_spec(spec):
    if not re.fullmatch(r'cccontract[a-z0-9]{8,14}',spec['account']) or spec['container']!='models':
        raise ValueError('Only the private project model container is permitted')
    names=set()
    if not spec['files']:raise ValueError('Empty cloud manifest')
    for item in spec['files']:
        name=item['name'];digest=item['sha256']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',name) or name in names:
            raise ValueError('Cloud manifest requires unique safe basenames')
        if not re.fullmatch('[a-f0-9]{64}',digest) or item['blob']!=digest+'/'+name:
            raise ValueError('Cloud blob identity is not bound to its digest')
        if type(item['bytes']) is not int or not 0<item['bytes']<=8*2**30:
            raise ValueError('Invalid model blob length')
        names.add(name)
    return spec


def imds_token():
    url='http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request(url,headers={'Metadata':'true'}),timeout=10) as response:
        value=json.loads(response.read(65536))
    return value['access_token']


def download(spec,output,credential=imds_token,open_url=urllib.request.urlopen,retry_seconds=300):
    validate_spec(spec);output=Path(output)
    output.mkdir(parents=True,exist_ok=True,mode=0o700)
    receipt={'schema_version':1,'scope':'CLOUD_MODEL_BYTE_TRANSFER_ONLY','account':spec['account'],'container':'models','files':[]}
    for item in spec['files']:
        target=output/item['name'];temporary=output/(item['name']+'.part')
        if target.exists() or target.is_symlink() or temporary.exists() or temporary.is_symlink():
            raise ValueError('Refusing to overwrite an existing download')
        url=f"https://{spec['account']}.blob.core.windows.net/models/{item['blob']}"
        deadline=time.monotonic()+retry_seconds
        while True:
            try:
                request=urllib.request.Request(url,headers={'Authorization':'Bearer '+credential(),'x-ms-version':'2023-11-03'})
                response=open_url(request,timeout=60)
                break
            except urllib.error.HTTPError as error:
                if error.code not in (401,403,429,500,502,503,504) or time.monotonic()>=deadline:raise
                time.sleep(min(5,max(0,deadline-time.monotonic())))
        digest=hashlib.sha256();size=0
        try:
            with response,temporary.open('xb') as file:
                for data in iter(lambda:response.read(8*2**20),b''):
                    size+=len(data)
                    if size>item['bytes']:raise ValueError('Cloud object is larger than its frozen length')
                    digest.update(data);file.write(data)
                file.flush();os.fsync(file.fileno())
            if size!=item['bytes'] or digest.hexdigest()!=item['sha256']:
                raise ValueError('Cloud object byte verification failed')
            temporary.chmod(0o444);temporary.replace(target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        receipt['files'].append({**item,'verified':True})
        print(json.dumps({'name':item['name'],'bytes':size,'sha256':digest.hexdigest(),'verified':True}),flush=True)
    return receipt


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--receipt',type=Path)
    parser.add_argument('--token-file',type=Path,help='Local CPU qualification only; Azure VM defaults to its managed identity')
    args=parser.parse_args()
    credential=(lambda:json.loads(args.token_file.read_text())['accessToken']) if args.token_file else imds_token
    receipt=download(json.loads(args.manifest.read_text()),args.output,credential=credential)
    if args.receipt:
        with args.receipt.open('x') as file:json.dump(receipt,file,indent=2);file.write('\n')


if __name__=='__main__':main()
