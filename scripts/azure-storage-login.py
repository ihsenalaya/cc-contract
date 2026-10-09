"""Native Linux device authentication using Microsoft's Azure CLI client."""
import json
import argparse
import base64
import os
from pathlib import Path
import time

import msal

parser=argparse.ArgumentParser()
parser.add_argument('--silent',action='store_true')
args=parser.parse_args()
os.umask(0o077)
state=Path.home()/'.local/state/cc-contract/artifact-store'
tenant=json.loads((state/'tenant.json').read_text())['tenant']
cache=msal.SerializableTokenCache()
cache_file=state/'native-msal-cache.json'
if cache_file.exists():cache.deserialize(cache_file.read_text())
app=msal.PublicClientApplication('04b07795-8ddb-461a-bbee-02f9e1bf7b46',authority='https://login.microsoftonline.com/'+tenant,token_cache=cache)
scopes=['https://storage.azure.com/.default']
accounts=app.get_accounts()
result=app.acquire_token_silent(scopes,accounts[0]) if accounts else None
if not result or 'access_token' not in result:
    if args.silent:raise RuntimeError('Native Azure login requires renewed device authentication')
    flow=app.initiate_device_flow(scopes=scopes)
    if 'user_code' not in flow:raise RuntimeError('Unable to start Azure device login: '+str(flow.get('error')))
    print(flow['message'],flush=True)
    deadline=time.time()+flow['expires_in']
    result=app.acquire_token_by_device_flow(flow,exit_condition=lambda _:time.time()>deadline)
if 'access_token' not in result:raise RuntimeError('Azure login failed: '+str(result.get('error')))
claims=json.loads(base64.urlsafe_b64decode(result['access_token'].split('.')[1]+'=='))
expected=json.loads((state/'inputs.json').read_text())['principal_id']
if claims.get('oid','').lower()!=expected.lower():raise RuntimeError('Use the Azure account that created this project storage')
cache_file.write_text(cache.serialize());cache_file.chmod(0o600)
token_file=state/'storage-token.json'
token_file.write_text(json.dumps({'accessToken':result['access_token']}));token_file.chmod(0o600)
print('Native Azure authentication ready; token retained privately.',flush=True)
