"""Run a registry operation using temporary RAM credentials from existing gh auth."""
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    if len(sys.argv)<2:raise SystemExit('usage: with-ghcr-auth.py COMMAND [ARGS...]')
    quiet={k:v for k,v in os.environ.items() if k!='GH_DEBUG'}
    token=quiet.get('GH_TOKEN') or quiet.get('GITHUB_TOKEN')
    if not token:
        # Older installed gh versions lack `auth token`; use the existing
        # protected credential, as the approved guest pull runner already does.
        match=re.search(r'^\s+oauth_token:\s*(\S+)\s*$',(Path.home()/'.config/gh/hosts.yml').read_text(),re.M)
        if not match:raise RuntimeError('Existing GHCR credential unavailable')
        token=match.group(1)
    directory=Path(tempfile.mkdtemp(prefix='cc-contract-ghcr-',dir='/dev/shm'))
    environment={**quiet,'DOCKER_CONFIG':str(directory),'DOCKER_HOST':os.environ.get('DOCKER_HOST','unix:///var/run/docker.sock')}
    environment.pop('DOCKER_CONTEXT',None)
    try:
        subprocess.run(['docker','login','ghcr.io','--username','ihsenalaya','--password-stdin'],
                       input=token+'\n',text=True,env=environment,capture_output=True,check=True)
        return subprocess.run(sys.argv[1:],env=environment).returncode
    finally:
        shutil.rmtree(directory)


if __name__=='__main__':raise SystemExit(main())
