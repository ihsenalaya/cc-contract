"""One approved, recovery-only retained-VM window. Never launches experiments."""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('window',ROOT/'scripts/hdsc-window.py')
window=importlib.util.module_from_spec(spec);spec.loader.exec_module(window)
retained=window.retained
SOURCE_NAMES=('scripts/recover-hdsc-window.py','scripts/hdsc-recovery.py',
              'scripts/hdsc-window.py','scripts/continuity-window.py')
POLICY=dict(protocol='hdsc-recovery-only-v1',previous_window='hdsc-eval-1010b',
            previous_plan_sha256='28e07560b63ecd77b86d6953413ce64d989eaee679e9e21efc31f6d601f59ff2',
            max_minutes=10,budget_usd=2,experiment_jobs=0,creates=0,destroys=0,
            vm_id=retained.VM,vm_uuid=retained.UUID,disk_uuid=retained.DISK_UUID,
            stop_policy='DEALLOCATE_AND_RETAIN')


def sources():
    return {name:window.sha(ROOT/name) for name in SOURCE_NAMES}


def validate(plan,receipt,digest,now):
    if any(plan.get(k)!=v for k,v in POLICY.items()) or plan.get('source_files_sha256')!=sources():
        raise ValueError('Recovery-only plan or frozen sources changed')
    if (receipt.get('approved') is not True or receipt.get('approved_by')!='user' or
        receipt.get('plan_sha256')!=digest or receipt.get('reuse_completed_authorization') is not False or
        any(receipt.get(k)!=POLICY[k] for k in ('protocol','max_minutes','budget_usd','experiment_jobs'))):
        raise ValueError('Fresh approval of this recovery-only plan required')
    stamp=datetime.fromisoformat(receipt['approved_utc'])
    if stamp.tzinfo is None or not 0 <= (now-stamp).total_seconds()<=3600:
        raise ValueError('Approval is stale or invalid')


def ssh_command():
    state=window.STATE
    outputs=json.loads((state/'work-sample-1009b/outputs.json').read_text())
    return ['ssh','-F','/dev/null','-i',str(state/'work-sample-1009b/id_ed25519'),
            '-o','BatchMode=yes','-o','ConnectTimeout=5','-o','ServerAliveInterval=10',
            '-o','ServerAliveCountMax=2','-o','StrictHostKeyChecking=yes',
            '-o','UserKnownHostsFile='+str(state/'fixed-work-1010a/known_hosts'),
            'cccontract@'+outputs['ssh_address']['value']]


def transfer(ssh,directory):
    # The helper can only inspect Docker and read the selected evidence directory.
    # No registry login, image pull, workload launch, or original-file mutation.
    with (directory/'originals.tar.gz').open('xb') as out:
        subprocess.run(ssh+['sudo -n python3 - --window hdsc-eval-1010b'],
            input=(ROOT/'scripts/hdsc-recovery.py').read_bytes(),stdout=out,
            stderr=subprocess.PIPE,check=True,timeout=90)


def verify(directory,plan):
    window.verify_archive(directory/'originals.tar.gz',directory)
    with tarfile.open(directory/'originals.tar.gz') as archive:
        old=archive.extractfile('previous-plan.json').read()
        core=archive.extractfile('originals/data/core/jobs.jsonl').read()
    if hashlib.sha256(old).hexdigest()!=plan['previous_plan_sha256']:
        raise ValueError('Recovered guest plan identity mismatch')
    if hashlib.sha256(core).hexdigest()!=plan['completed_core_jobs_sha256']:
        raise ValueError('Recovered core differs from previously verified checkpoint')
    window.write(directory/'provenance.json',dict(previous_plan_verified=True,
        completed_core_checkpoint_verified=True,experiment_jobs=0,originals_modified=False))


def review(directory):
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    live=retained.inventory();window.write(directory/'inventory.json',live)
    collection=json.loads((window.STATE/'hdsc-eval-1010b/core-checkpoint/collection.json').read_text())
    plan={**POLICY,'source_files_sha256':sources(),'approval_granted':False,
          'guard_id':live['guard']['id'],
          'guard_definition_sha256':hashlib.sha256(json.dumps(live['guard']['properties']['definition'],sort_keys=True).encode()).hexdigest(),
          'completed_core_jobs_sha256':collection['files_sha256']['data/core/jobs.jsonl'],
          'linux_retail_usd_per_hour':6.98,'compute_at_maximum_minutes_usd':6.98/6,
          'expected_minutes':[3,6],'SSH_allowance_seconds':240,'transfer_allowance_seconds':90,
          'independent_guard_minutes':7,'post_transfer_verification':'LOCAL_AFTER_DEALLOCATION'}
    window.write(directory/'plan.json',plan)
    print(json.dumps(dict(plan_sha256=window.sha(directory/'plan.json'),H100='DEALLOCATED',experiment_jobs=0)))


def execute(directory,approval):
    plan=json.loads((directory/'plan.json').read_text())
    validate(plan,json.loads(approval.read_text()),window.sha(directory/'plan.json'),datetime.now(timezone.utc))
    window.write(directory/'execution-attempt.json',dict(utc=datetime.now(timezone.utc).isoformat()))
    live=retained.inventory();definition=live['guard']['properties']['definition']
    if live['guard']['id']!=plan['guard_id'] or hashlib.sha256(json.dumps(definition,sort_keys=True).encode()).hexdigest()!=plan['guard_definition_sha256']:
        raise ValueError('Guard changed since review')
    end=datetime.now(timezone.utc)+timedelta(minutes=7)
    renewed=copy.deepcopy(definition)
    renewed['actions']['ExpiryGuard']['expression']['greaterOrEquals'][1]="@ticks('"+end.strftime('%Y-%m-%dT%H:%M:%SZ')+"')"
    body=directory/'guard-update.json';window.write(body,retained.guard_update_body(live['guard'],renewed))
    window.az('rest','--method','put','--url','https://management.azure.com'+plan['guard_id']+'?api-version=2019-05-01','--body','@'+str(body))
    actual=window.az('resource','show','--ids',plan['guard_id'],'--api-version','2019-05-01');retained.validate_guard(actual)
    if actual['properties']['definition']!=renewed or any(actual.get(k)!=live['guard'].get(k) for k in ('id','identity','location','tags')):
        raise ValueError('Guard readback mismatch; VM stays off')
    window.write(directory/'renewed-guard.json',actual);retained.inventory()
    ssh=ssh_command()
    with window.allocated_window(directory):
        deadline=time.monotonic()+240
        while subprocess.run(ssh+['true'],capture_output=True,timeout=10).returncode:
            if time.monotonic()>deadline:raise RuntimeError('Recovery SSH deadline reached')
            time.sleep(5)
        transfer(ssh,directory)
    # The expensive resource is released before archive checking and diagnosis.
    verify(directory,plan)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('review','run'))
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--approval',type=Path)
    args=parser.parse_args();os.umask(0o077)
    if args.action=='review':review(args.directory)
    else:
        if args.approval is None:parser.error('Approval receipt required')
        execute(args.directory,args.approval)
