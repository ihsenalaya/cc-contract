"""Create an immutable local model/image bundle before requesting a GPU window."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    value=hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(8*1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model-directory',required=True,type=Path)
    parser.add_argument('--corpus',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
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
    for name,expected in model['file_sha256'].items():
        file=args.model_directory/name
        if Path(name).name!=name or file.is_symlink() or not file.is_file() or sha(file)!=expected:raise ValueError('Model data changed after download verification')
    args.output.mkdir(parents=True,exist_ok=False,mode=0o700);archive=args.output/'model-bundle.tar.gz'
    from importlib.util import spec_from_file_location,module_from_spec
    spec=spec_from_file_location('model_preparation',ROOT/'scripts/prepare-model.py')
    preparation=module_from_spec(spec);spec.loader.exec_module(preparation)
    needed=sum((args.model_directory/name).stat().st_size for name in model['file_sha256'])
    if preparation.available_bytes(args.output)<needed+4*2**30:
        raise RuntimeError('Model bundle requires sufficient physical space plus 4 GiB reserve')
    # Fast gzip is prepared entirely locally. Only pinned model data + corpus
    # enter the archive, never arbitrary caches or account information.
    with tarfile.open(archive,'w:gz',compresslevel=1) as tar:
        for name in sorted(model['file_sha256']):tar.add(args.model_directory/name,arcname=name,recursive=False)
        tar.add(args.model_directory/'cc-model-manifest.json',arcname='cc-model-manifest.json',recursive=False)
        tar.add(args.corpus,arcname='inference-corpus.json',recursive=False)
    bundle={'schema_version':1,'scope':'PREPARED_GPU_PILOT_NOT_EXECUTED','images':images,'local_image_gates':gates,
            'model_archive':str(archive.resolve()),'model_archive_sha256':sha(archive),'model_archive_bytes':archive.stat().st_size,
            'model_revision':model['revision'],'model_manifest_sha256':sha(args.model_directory/'cc-model-manifest.json'),
            'corpus_filename':'inference-corpus.json','corpus_sha256':sha(args.corpus),'approval_granted':False,
            'workloads':['E0_native_reference','E2_96_IR_cases_optional_capabilities','E1_E7_18_float_component_records','E7_24_paired_Qwen_prompts'],
            'comparative_E4_E5_campaigns_included':False}
    (args.output/'workload-bundle.json').write_text(json.dumps(bundle,indent=2)+'\n')
    for file in args.output.iterdir():file.chmod(0o444)
    print(json.dumps({k:v for k,v in bundle.items() if k!='model_archive'},indent=2))


if __name__=='__main__':main()
