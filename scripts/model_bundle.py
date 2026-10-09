"""Deterministic tar transport of pinned model data without a duplicate disk copy."""
import hashlib
import json
from pathlib import Path
import tarfile


class HashingWriter:
    def __init__(self, destination=None):
        self.destination=destination;self.digest=hashlib.sha256();self.size=0
    def write(self, data):
        self.digest.update(data);self.size+=len(data)
        if self.destination is not None:self.destination.write(data)
        return len(data)


def stream(directory, corpus, destination=None):
    directory=Path(directory);corpus=Path(corpus)
    manifest=json.loads((directory/'cc-model-manifest.json').read_text())
    sources={name:directory/name for name in manifest['file_sha256']}
    sources.update({'cc-model-manifest.json':directory/'cc-model-manifest.json','inference-corpus.json':corpus})
    writer=HashingWriter(destination)
    with tarfile.open(fileobj=writer,mode='w|',format=tarfile.PAX_FORMAT) as archive:
        for name,file in sorted(sources.items()):
            if Path(name).name!=name or file.is_symlink() or not file.is_file():
                raise ValueError('Model bundle only permits regular basename files')
            info=tarfile.TarInfo(name);info.size=file.stat().st_size
            info.uid=info.gid=10001;info.mode=0o444;info.mtime=0
            with file.open('rb') as data:archive.addfile(info,data)
    return {'sha256':writer.digest.hexdigest(),'bytes':writer.size}
