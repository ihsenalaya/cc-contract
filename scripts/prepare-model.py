"""Download only revision-pinned model data locally; no remote model code."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import urllib.request

REPOSITORY='Qwen/Qwen2.5-7B-Instruct'
REVISION='a09a35458c702b33eeacc393d103063234e8bc28'
SMALL={'LICENSE','config.json','generation_config.json','merges.txt','model.safetensors.index.json',
       'tokenizer.json','tokenizer_config.json','vocab.json'}


def file_hash(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def available_bytes(destination):
    free=shutil.disk_usage(destination).free
    if 'microsoft' in platform.release().lower() and Path('/mnt/c').is_dir():
        # The current workspace and WSL backing disks reside on C:. Query its
        # mounted filesystem directly, avoiding unreliable Windows interop.
        free=min(free,shutil.disk_usage('/mnt/c').free)
    elif 'microsoft' in platform.release().lower() and shutil.which('powershell.exe'):
        response=subprocess.check_output(['powershell.exe','-NoProfile','-Command',
                 'Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Select-Object DeviceID,FreeSpace | ConvertTo-Json -Compress'])
        disks=json.loads(response.decode()); disks=[disks] if isinstance(disks,dict) else disks
        free=min(free,next(d['FreeSpace'] for d in disks if d['DeviceID']=='C:'))
    return free


def download(destination,weights=False):
    destination.mkdir(parents=True,exist_ok=True,mode=0o700)
    with urllib.request.urlopen(f'https://huggingface.co/api/models/{REPOSITORY}/revision/{REVISION}?blobs=true',timeout=60) as response:
        metadata=json.load(response)
    if metadata['sha']!=REVISION:
        raise ValueError('Model revision did not match pinned identifier')
    selected=[s for s in metadata['siblings'] if s['rfilename'] in SMALL or (weights and s['rfilename'].endswith('.safetensors'))]
    existing={p.name:p for p in destination.iterdir() if p.is_file()}
    missing=sum(s['size'] for s in selected if s['rfilename'] not in existing)
    if available_bytes(destination)<missing+4*2**30:
        raise RuntimeError(f'Insufficient physical storage: need {missing/2**30:.2f} GiB plus 4 GiB reserve')
    hashes={}
    for item in selected:
        name=item['rfilename']
        if Path(name).name!=name:
            raise ValueError('Model data must use basename-only paths')
        target=destination/name; expected=item.get('lfs',{}).get('sha256')
        if not target.exists() or target.stat().st_size!=item['size'] or (expected and file_hash(target)!=expected):
            temporary=destination/(name+'.partial')
            request=f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}'
            with urllib.request.urlopen(request,timeout=180) as response, temporary.open('wb') as file:
                shutil.copyfileobj(response,file,length=8*1024*1024)
            if temporary.stat().st_size!=item['size'] or (expected and file_hash(temporary)!=expected):
                raise ValueError('Downloaded model file integrity mismatch')
            temporary.replace(target)
        hashes[name]=file_hash(target)
    manifest={'repository':REPOSITORY,'revision':REVISION,'file_sha256':hashes,'weights_downloaded':weights,
              'trust_remote_code':False,'source':'https://huggingface.co/'+REPOSITORY,'redistribution':'model license applies'}
    (destination/'cc-model-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def corpus(directory,output):
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(directory,local_files_only=True,trust_remote_code=False)
    cases=[]
    for length in (32,128,512):
        for index in range(8):
            raw=(f'Record {index}. Compare the integer values and describe their order. ')*(length+1)
            ids=tokenizer(raw,add_special_tokens=False)['input_ids'][:length]
            text=tokenizer.decode(ids,clean_up_tokenization_spaces=False)
            if tokenizer(text,add_special_tokens=False)['input_ids']!=ids:
                raise ValueError('Tokenizer round-trip did not preserve exact frozen length')
            forced=tokenizer('\nAnswer: fixed.',add_special_tokens=False)['input_ids']
            cases.append({'id':f'synthetic-{length}-{index}','length':length,'text':text,'token_ids':ids,
                          'forced_continuation':forced,'source':'project-generated public synthetic text',
                          'tokenizer_model':REPOSITORY,'tokenizer_revision':REVISION})
    with output.open('x') as file:json.dump(cases,file,indent=2);file.write('\n')
    return {'cases':len(cases),'corpus_sha256':file_hash(output),'scope':'TOKENIZER_ONLY_NO_MODEL_INFERENCE'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['download','corpus'])
    parser.add_argument('--directory',required=True,type=Path);parser.add_argument('--weights',action='store_true')
    parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.action=='corpus' and not args.output:parser.error('corpus requires --output')
    result=download(args.directory,args.weights) if args.action=='download' else corpus(args.directory,args.output)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
