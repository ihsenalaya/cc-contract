"""Install the pinned official Linux Azure CLI in project-private user state.

Reuse the user's existing authorized native device session when available.
Never writes authentication material into the repository or invokes Windows.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


def main():
    os.umask(0o077)
    root = Path(__file__).resolve().parents[1]
    state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))) / 'cc-contract'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    venv = state / 'azure-native-cli-venv'
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(venv)], check=True)
    python = venv / 'bin/python'
    # Ubuntu's system Python may lack ensurepip. Bootstrap only this venv.
    version = f'python{sys.version_info.major}.{sys.version_info.minor}'
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', '--upgrade',
                    '--target', str(venv/'lib'/version/'site-packages'), 'pip==25.2'], check=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '--no-cache-dir', '-r',
                    str(root/'scripts/requirements-azure-cli-linux.txt')], check=True)
    subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
    config = state / 'azure-native-cli-config'
    config.mkdir(exist_ok=True, mode=0o700)
    config.chmod(0o700)
    cache = config / 'msal_token_cache.json'
    authorized = state / 'artifact-store/native-msal-cache.json'
    if not cache.exists() and authorized.exists():
        shutil.copyfile(authorized, cache)
        cache.chmod(0o600)
    profile = config / 'azureProfile.json'
    account = state / 'preflight-20261009-next/azure-account.json'
    if not profile.exists() and account.exists():
        raw = account.read_bytes()
        try:
            parsed = json.loads(raw.decode('utf-8-sig'))
        except UnicodeDecodeError:
            parsed = json.loads(raw.decode('cp1252'))
        profile.write_text(json.dumps({'installationId': str(uuid.uuid4()), 'subscriptions': [parsed]}))
        profile.chmod(0o600)
    env = {**os.environ, 'AZURE_CONFIG_DIR': str(config)}
    if profile.exists():
        subprocess.run([str(venv/'bin/az'), 'account', 'get-access-token', '--resource',
                        'https://management.azure.com/', '--query', '{expiresOn:expiresOn,tokenType:tokenType}',
                        '-o', 'json', '--only-show-errors'], env=env, check=True)
        print('Official native CLI and existing authorized session verified; no resources created.')
    else:
        print('Official native CLI installed. Authenticate with its az login --use-device-code and this protected AZURE_CONFIG_DIR.')


if __name__ == '__main__':
    main()
