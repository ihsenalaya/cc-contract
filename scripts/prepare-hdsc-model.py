"""Fetch the fixed small trained model into private storage and verify every byte."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();manifest=json.loads((ROOT/'results/manifests/hdsc-model-assets.json').read_text())
    args.output.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name,expected in manifest['files'].items():
        if Path(name).name!=name:raise ValueError('Invalid model filename')
        target=args.output/name
        if not target.exists():
            url=f"https://huggingface.co/{manifest['model']}/resolve/{manifest['revision']}/{name}"
            with urllib.request.urlopen(url,timeout=90) as response:payload=response.read(expected['bytes']+1)
            if len(payload)!=expected['bytes'] or hashlib.sha256(payload).hexdigest()!=expected['sha256']:
                raise ValueError('Downloaded model differs from pinned artifact')
            with target.open('xb') as file:file.write(payload)
        if target.is_symlink() or target.stat().st_size!=expected['bytes'] or hashlib.sha256(target.read_bytes()).hexdigest()!=expected['sha256']:
            raise ValueError('Existing model differs; preserve it and investigate')
    receipt=args.output/'artifact-manifest.json'
    if receipt.exists() and json.loads(receipt.read_text())!=manifest:raise ValueError('Existing manifest differs')
    if not receipt.exists():receipt.write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'model':manifest['model'],'revision':manifest['revision'],'verified_bytes':sum(x['bytes'] for x in manifest['files'].values())}))


if __name__=='__main__':main()
