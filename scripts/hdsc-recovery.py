"""Read-only retained-guest preflight and bounded archive; invoked over approved SSH.

No container is started, stopped or deleted. Originals are never rewritten.
The caller verifies all streamed hashes before admitting a new GPU workload.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

PREVIOUS = Path('/home/cccontract/cc-hdsc-hdsc-eval-1010a')
MAX_BYTES = 2 * 1024**3
MAX_FILES = 10000


def preflight(containers):
    for container in containers:
        config = container.get('HostConfig', {})
        gpu = config.get('Runtime') == 'nvidia' or any(
            'gpu' in group for request in config.get('DeviceRequests') or []
            for group in request.get('Capabilities', []))
        owned = container.get('Name', '').lstrip('/').startswith('cc-hdsc-')
        if container['State']['Running'] and (gpu or owned):
            raise ValueError('An existing GPU/HDSC container is running; stop the window')


def archive(root, containers, output):
    preflight(containers)
    if root.is_symlink() or (root/'evidence').is_symlink() or not (root/'evidence').is_dir():
        raise ValueError('Retained evidence directory is missing or unsafe')
    files = []
    for file in sorted((root/'evidence').rglob('*')):
        if file.is_symlink():raise ValueError('Evidence symlink rejected')
        if file.is_dir():continue
        if not file.is_file():raise ValueError('Non-regular evidence rejected')
        files.append(('originals/'+str(file.relative_to(root/'evidence')), file))
    for name in ('plan.json', 'approval.json', 'run-hdsc-host.sh', 'run-hdsc-section.py'):
        file=root/name
        if file.is_symlink() or not file.is_file():raise ValueError('Retained control file missing or unsafe')
        files.append(('previous-'+name, file))
    if len(files)>MAX_FILES or sum(f.stat().st_size for _,f in files)>MAX_BYTES:
        raise ValueError('Retained evidence exceeds recovery limit')
    hashes={}
    with tarfile.open(fileobj=output, mode='w|gz') as out:
        def add(name, data):
            entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o600
            out.addfile(entry,io.BytesIO(data));hashes[name]=hashlib.sha256(data).hexdigest()
        add('container-inspect.json',(json.dumps(containers,sort_keys=True)+'\n').encode())
        for name,file in files:
            before=file.stat();digest=hashlib.sha256()
            with file.open('rb') as source:
                for block in iter(lambda:source.read(1024**2),b''):digest.update(block)
            with file.open('rb') as source:
                entry=tarfile.TarInfo(name);entry.size=before.st_size;entry.mode=0o600
                out.addfile(entry,source)
            after=file.stat()
            if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
                raise ValueError('Retained evidence changed while copying')
            hashes[name]=digest.hexdigest()
        add('hashes.json',(json.dumps(hashes,sort_keys=True,indent=2)+'\n').encode())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window',choices=('hdsc-eval-1010a','hdsc-eval-1010b'),default='hdsc-eval-1010a')
    args=parser.parse_args()
    ids=subprocess.check_output(['docker','ps','-aq'],timeout=15).decode().split()
    containers=json.loads(subprocess.check_output(['docker','inspect',*ids],timeout=15)) if ids else []
    archive(PREVIOUS.parent/('cc-hdsc-'+args.window),containers,sys.stdout.buffer)


if __name__=='__main__':main()
