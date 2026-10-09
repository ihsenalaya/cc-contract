"""Create an immutable local model/image bundle before requesting a GPU window."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cc_contract.cloud_model import validate_spec

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    value=hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(8*1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model-directory',required=True,type=Path)
    parser.add_argument('--corpus',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--stream-model',action='store_true',help='Precompute deterministic tar hash locally and transfer without duplicate storage')
    parser.add_argument('--model-receipt',type=Path,help='Use the complete verified Azure backup instead of local weight shards')
    args=parser.parse_args();model=json.loads((args.model_directory/'cc-model-manifest.json').read_text())
    if not model['weights_downloaded']:parser.error('All model shards must be prepared locally')
    corpus=json.loads(args.corpus.read_text())
    if len(corpus)!=24 or sorted(c['length'] for c in corpus)!=[32]*8+[128]*8+[512]*8:parser.error('Frozen corpus incomplete')
    images={};gates={}
    for kind in ('cuda','ir','torch'):
        directory=ROOT/'.local'/kind;gate=json.loads((directory/'kind-verified.json').read_text())
        inspection=json.loads((directory/'inspect.json').read_text())[0]
        if not gate['verified'] or gate['image_id']!=inspection['Id']:raise ValueError('Image lacks matching Kind qualification')
        image=(directory/'remote-digest').read_text().strip();registry=json.loads((directory/'registry.json').read_text())
        if image.rsplit('@',1)[1]!=registry['digest']:raise ValueError('Published registry digest mismatch')
        images[kind]=image;gates[kind]={'git_commit':gate['git_commit'],'image_id':gate['image_id'],'kind_gate_sha256':sha(directory/'kind-verified.json')}
    cloud=None
    if args.model_receipt:
        if args.stream_model:parser.error('Select one model transport')
        receipt=json.loads(args.model_receipt.read_text())
        storage=json.loads((args.model_receipt.parent/'outputs.json').read_text())
        expected={**model['file_sha256'],'cc-model-manifest.json':sha(args.model_directory/'cc-model-manifest.json'),'inference-corpus.json':sha(args.corpus)}
        if receipt['account']!=storage['account_name']['value'] or receipt['container']!='models':raise ValueError('Backup belongs to a different storage container')
        rows=receipt['files']
        if len(rows)!=len(expected) or {Path(r['local_path']).name:r['sha256'] for r in rows}!=expected or not all(r['remote_bytes_verified'] is True for r in rows):
            raise ValueError('Model backup is incomplete or changed')
        cloud=validate_spec({'account':receipt['account'],'container':'models','files':[{'name':Path(r['local_path']).name,'blob':r['blob'],'bytes':r['bytes'],'sha256':r['sha256']} for r in rows]})
        cloud['resource_scope']=storage['account_id']['value']+'/blobServices/default/containers/models'
    else:
        for name,expected in model['file_sha256'].items():
            file=args.model_directory/name
            if Path(name).name!=name or file.is_symlink() or not file.is_file() or sha(file)!=expected:raise ValueError('Model data changed after download verification')
    args.output.mkdir(parents=True,exist_ok=False,mode=0o700);archive=args.output/'model-bundle.tar.gz'
    from importlib.util import spec_from_file_location,module_from_spec
    spec=spec_from_file_location('model_preparation',ROOT/'scripts/prepare-model.py')
    preparation=module_from_spec(spec);spec.loader.exec_module(preparation)
    needed=0 if cloud else sum((args.model_directory/name).stat().st_size for name in model['file_sha256'])
    reserve=(1 if args.stream_model or cloud else 4)*2**30
    if preparation.available_bytes(args.output)<(0 if args.stream_model or cloud else needed)+reserve:
        raise RuntimeError('Insufficient physical storage for the selected model transport and evidence reserve')
    # Fast gzip is prepared entirely locally. Only pinned model data + corpus
    # enter the archive, never arbitrary caches or account information.
    if cloud:
        packed={'sha256':None,'bytes':sum(r['bytes'] for r in cloud['files'])}
        transport='AZURE_BLOB_IMDS'
    elif args.stream_model:
        from model_bundle import stream
        packed=stream(args.model_directory,args.corpus)
        transport='DETERMINISTIC_TAR_STREAM'
    else:
        with tarfile.open(archive,'w:gz',compresslevel=1) as tar:
            for name in sorted(model['file_sha256']):tar.add(args.model_directory/name,arcname=name,recursive=False)
            tar.add(args.model_directory/'cc-model-manifest.json',arcname='cc-model-manifest.json',recursive=False)
            tar.add(args.corpus,arcname='inference-corpus.json',recursive=False)
        packed={'sha256':sha(archive),'bytes':archive.stat().st_size}
        transport='PREPARED_GZIP_ARCHIVE'
    bundle={'schema_version':1,'scope':'PREPARED_GPU_PILOT_NOT_EXECUTED','images':images,'local_image_gates':gates,
            'transport':transport,'model_directory':str(args.model_directory.resolve()),'corpus_path':str(args.corpus.resolve()),
            'model_archive':None if args.stream_model or cloud else str(archive.resolve()),'model_archive_sha256':packed['sha256'],'model_archive_bytes':packed['bytes'],
            'model_revision':model['revision'],'model_manifest_sha256':sha(args.model_directory/'cc-model-manifest.json'),
            'corpus_filename':'inference-corpus.json','corpus_sha256':sha(args.corpus),'approval_granted':False,
            'workloads':['E0_native_reference','E2_96_IR_cases_optional_capabilities','E1_E7_18_float_component_records','E7_24_paired_Qwen_prompts'],
            'comparative_E4_E5_campaigns_included':False}
    if cloud:
        gate=json.loads((ROOT/'.local/cloud-model-kind/verified.json').read_text())
        cloud_image=(ROOT/'.local/images/remote-digest').read_text().strip()
        registry=json.loads((ROOT/'.local/images/registry-manifest.json').read_text())
        inspection=json.loads((ROOT/'.local/images/inspect.json').read_text())[0]
        if not gate['verified'] or gate['image_id']!=inspection['Id'] or gate['git_commit']!=inspection['Config']['Labels']['org.opencontainers.image.revision'] or gate['downloader_sha256']!=sha(ROOT/'src/cc_contract/cloud_model.py') or cloud_image.rsplit('@',1)[1]!=registry['digest']:
            raise ValueError('Cloud downloader lacks matching Kind and registry verification')
        bundle['model_cloud']=cloud
        bundle['cloud_transport_image']=cloud_image
        bundle['cloud_transport_kind_sha256']=sha(ROOT/'.local/cloud-model-kind/verified.json')
        bundle['cloud_downloader_sha256']=sha(ROOT/'src/cc_contract/cloud_model.py')
        bundle['model_receipt_sha256']=sha(args.model_receipt)
    (args.output/'workload-bundle.json').write_text(json.dumps(bundle,indent=2)+'\n')
    for file in args.output.iterdir():file.chmod(0o444)
    print(json.dumps({k:v for k,v in bundle.items() if k!='model_archive'},indent=2))


if __name__=='__main__':main()
