"""Bind the existing qualified images and completed local sample gate before plan."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--kind-receipt',required=True,type=Path)
    parser.add_argument('--spec',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    loader=importlib.util.spec_from_file_location('sample',ROOT/'scripts/run-sequential-sample.py')
    sample=importlib.util.module_from_spec(loader);loader.loader.exec_module(sample)
    spec=json.loads(args.spec.read_text())
    if spec!=sample.make_spec('cuda'):raise ValueError('GPU sample specification changed')
    kind=json.loads(args.kind_receipt.read_text())
    if not kind['verified'] or kind['gpu_executed'] is not False or kind['harness_sha256']!=sample.harness_sha256() or kind['image_digest']!=sample.IMAGE_DIGEST:
        raise ValueError('Matching CPU sample qualification required')
    if {row['node'] for row in kind['workers']}!={'cc-contract-worker','cc-contract-worker2'} or any(row['completed_jobs']!=14 or row['gpu_executed'] is not False for row in kind['workers']):
        raise ValueError('Both CPU workers must finish all fourteen sequential sample jobs')
    images={};gates={}
    for name in ('cuda','ir'):
        directory=ROOT/'.local'/name
        gate=json.loads((directory/'kind-verified.json').read_text())
        inspection=json.loads((directory/'inspect.json').read_text())[0]
        image=(directory/'remote-digest').read_text().strip()
        registry=json.loads((directory/'registry.json').read_text())
        if not gate['verified'] or gate['image_id']!=inspection['Id'] or image.split('@')[1]!=registry['digest'] or gate['git_commit']!=inspection['Config']['Labels']['org.opencontainers.image.revision']:
            raise ValueError('Existing image qualification or immutable publication changed')
        expected_source=sample.SOURCE_COMMIT if name=='ir' else 'e8f34fddc62479a6995dcf260a4242e1494cc26b'
        if gate['git_commit']!=expected_source:raise ValueError('Pinned image source changed')
        images[name]=image;gates[name]={'image_id':inspection['Id'],'kind_gate_sha256':sha(directory/'kind-verified.json'),'source_commit':gate['git_commit']}
    if images['ir']!=sample.IMAGE_DIGEST:raise ValueError('Sample must use the qualified IR digest')
    bundle={'schema_version':1,'transport':'SEQUENTIAL_IR_SAMPLE','images':images,'image_gates':gates,
            'sample_spec_path':str(args.spec.resolve()),'sample_spec_sha256':sha(args.spec),
            'sample_harness_sha256':sample.harness_sha256(),'cpu_kind_receipt_sha256':sha(args.kind_receipt),
            'gpu_jobs_parallel':False,'model_download_required':False,'comparative_campaigns_included':False}
    with args.output.open('x') as output:json.dump(bundle,output,indent=2);output.write('\n')
    args.output.chmod(0o444)
    print(json.dumps({'bundle_file':str(args.output),'bundle_sha256':sha(args.output),'planned_jobs':14,'gpu_created':False}))


if __name__=='__main__':main()
