"""Review or execute one fresh, approved HDSC window on the retained VM.

Review is read-only in Azure. Run never creates or destroys resources. Shared
identity, guard PUT/readback and retained-VM checks come from the completed pilot.
"""
import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import time

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('retained',ROOT/'scripts/continuity-window.py')
retained=importlib.util.module_from_spec(spec);spec.loader.exec_module(retained)
STATE=retained.STATE
sha,write,az=retained.sha,retained.write,retained.az
RESUME = dict(version='hdsc-resume-v1', previous_window='hdsc-eval-1010a',
    previous_plan_sha256='9cbdc48695ecc666f66b9cc26aa5f08948c7bfb25b94cc0c6a0f631d94710ec5',
    captured_prefix_rows=52,
    captured_prefix_sha256='154cd2618584149720acdcd89311f7ba602e69e527f8f7f12749c4b8f3bfddc0',
    pooling='NONE_REPLACEMENT_MATRIX_DISCLOSE_PREVIOUS_EXPOSURE',
    expected_unsupported_tools=['memcheck','initcheck','synccheck'],
    expected_executed_jobs=433, expected_skipped_jobs=720)
AI_RESUME = dict(version='hdsc-ai-resume-v1',previous_window='hdsc-eval-1010b',
    previous_plan_sha256='28e07560b63ecd77b86d6953413ce64d989eaee679e9e21efc31f6d601f59ff2',
    captured_prefix_rows=1083,
    captured_prefix_sha256='38ea1e78ffbbe40cf68cd7987bcdcfda0039f72e52bae0d648b7957eeb3a2b2e',
    pooling='DISJOINT_NATIVE_AND_AI_SECTIONS_WITH_EXPLICIT_SOURCE_PROVENANCE',
    expected_executed_jobs=72,expected_skipped_jobs=0,development_graph_checks=2,
    reserved_AI_jobs=70,native_jobs=0)


def source_files():
    return sorted([*ROOT.glob('src/cc_contract/hdsc_*.py'),ROOT/'src/cuda/hdsc_dynamic_worker.cu',
        ROOT/'src/cuda/continuity_worker.cu',ROOT/'src/cc_contract/continuity_oracle.py',
        *ROOT.glob('experiments/hdsc-*.json'),*ROOT.glob('docs/paper/*.md'),
        ROOT/'scripts/hdsc-window.py',ROOT/'scripts/continuity-window.py',ROOT/'scripts/run-hdsc-host.sh',
        ROOT/'scripts/run-hdsc-section.py',ROOT/'results/manifests/hdsc-model-assets.json',
        ROOT/'scripts/analyze-hdsc-evaluation.py',ROOT/'scripts/audit-hdsc-rq2.py',ROOT/'scripts/audit-hdsc-development.py',
        ROOT/'docs/environment/final-h100-evaluation-plan.md',
        ROOT/'docs/environment/hdsc-resumption-plan.md',ROOT/'docs/environment/hdsc-ai-resumption-plan.md',ROOT/'scripts/hdsc-recovery.py',
        ROOT/'infrastructure/hdsc/Dockerfile',ROOT/'infrastructure/hdsc/Dockerfile.ai'])


def check_plan(plan):
    from cc_contract.hdsc_schedule import counts
    if (plan.get('protocol')!='hdsc-evaluation-v1' or plan.get('vm_id')!=retained.VM or
        plan.get('vm_uuid')!=retained.UUID or plan.get('disk_uuid')!=retained.DISK_UUID or
        plan.get('counts')!=counts() or (plan.get('max_minutes'),plan.get('budget_usd')) not in ((90,12),(30,4)) or
        plan.get('gpu_parallelism')!=1 or plan.get('creates')!=0 or plan.get('destroys')!=0):
        raise ValueError('Plan does not match the reviewed bounded HDSC protocol')
    if (plan['max_minutes']==30 and plan.get('resumption') not in (RESUME,AI_RESUME)) or (plan['max_minutes']==90 and plan.get('resumption') is not None):
        raise ValueError('Resumption policy and reduced allowance must match exactly')
    sections=['ai'] if plan.get('resumption')==AI_RESUME else ['core','ai']
    if plan.get('execution_sections',['core','ai'])!=sections:
        raise ValueError('Execution sections differ from the reviewed scope')
    for section in ('core','ai'):
        name='cc-contract-hdsc'+('-ai' if section=='ai' else '')
        if not re.fullmatch('ghcr.io/ihsenalaya/'+name+r'@sha256:[a-f0-9]{64}',plan['images'][section]):
            raise ValueError('Immutable qualified image required')
    expected={str(p.relative_to(ROOT)):sha(p) for p in source_files()}
    if plan['source_files_sha256']!=expected or plan['schedule_sha256']!=sha(ROOT/'experiments/hdsc-schedule-v1.json'):
        raise ValueError('Frozen sources changed; prepare a new reviewed plan')


def approval(plan, receipt, digest, now):
    check_plan(plan)
    if (receipt.get('approved') is not True or receipt.get('approved_by')!='user' or
        receipt.get('plan_sha256')!=digest or receipt.get('protocol')!=plan['protocol'] or
        receipt.get('max_minutes')!=plan['max_minutes'] or receipt.get('budget_usd')!=plan['budget_usd'] or
        receipt.get('reuse_completed_authorization') is not False):
        raise ValueError('Fresh explicit user approval of this exact plan is required')
    timestamp=datetime.fromisoformat(receipt['approved_utc'])
    if timestamp.tzinfo is None or not 0 <= (now-timestamp).total_seconds() <= 3600:
        raise ValueError('Approval must be fresh, timezone-aware and unused')


def review(args):
    from cc_contract.hdsc_schedule import counts
    args.directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    qualification=json.loads(args.qualification.read_text())
    if qualification['state']!='PASS_LOCAL_QUALIFICATION' or qualification['CI_conclusion']!='success':
        raise ValueError('Local qualification and source CI must be complete')
    live=retained.inventory();write(args.directory/'inventory.json',live)
    plan=dict(protocol='hdsc-evaluation-v1',vm_id=retained.VM,vm_uuid=retained.UUID,disk_uuid=retained.DISK_UUID,
        images=qualification['images'],source_commit=qualification['source_commit'],
        qualification_sha256=sha(args.qualification),source_files_sha256={str(p.relative_to(ROOT)):sha(p) for p in source_files()},
        schedule_sha256=sha(ROOT/'experiments/hdsc-schedule-v1.json'),counts=counts(),gpu_parallelism=1,
        creates=0,destroys=0,max_minutes=30,budget_usd=4,linux_retail_usd_per_hour=6.98,
        compute_at_maximum_minutes_usd=3.49,resumption=AI_RESUME if args.ai_only else RESUME,
        execution_sections=['ai'] if args.ai_only else ['core','ai'],guard_id=live['guard']['id'],
        guard_definition_sha256=hashlib.sha256(json.dumps(live['guard']['properties']['definition'],sort_keys=True).encode()).hexdigest(),
        approval_granted=False,stop_policy='DEALLOCATE_AND_RETAIN',
        source_CI=qualification['source_CI'],unmeasured_duration_assumption_minutes=[10,25])
    check_plan(plan);write(args.directory/'plan.json',plan)
    print(json.dumps({'plan_sha256':sha(args.directory/'plan.json'),'H100':'DEALLOCATED','STOP':'WAIT_FOR_FRESH_USER_APPROVAL'}))


def bundle(args, plan, section_approval):
    from cc_contract.hdsc_ai import verify_assets
    manifest=verify_assets(args.model)
    if manifest!=json.loads((ROOT/'results/manifests/hdsc-model-assets.json').read_text()):
        raise ValueError('Model differs from frozen public asset hashes')
    write(args.directory/'section-approval.json',section_approval)
    archive=args.directory/'input.tar'
    with tarfile.open(archive,'x') as out:
        for name in ('run-hdsc-host.sh','run-hdsc-section.py'):
            out.add(ROOT/'scripts'/name,arcname=name,recursive=False)
        out.add(args.directory/'plan.json',arcname='plan.json',recursive=False)
        out.add(args.directory/'section-approval.json',arcname='approval.json',recursive=False)
        for name in (*manifest['files'],'artifact-manifest.json'):
            out.add(args.model/name,arcname='model/'+name,recursive=False)
    return archive


def collect(ssh,remote,directory):
    archive=directory/'originals.tar.gz'
    with archive.open('xb') as out:
        subprocess.run(ssh+['tar -czf - -C '+shlex.quote(remote+'/evidence')+' .'],stdout=out,stderr=subprocess.PIPE,check=True,timeout=120)
    verify_archive(archive,directory)


def verify_archive(archive,directory):
    total=0;hashes={};original_hashes=None
    with tarfile.open(archive,'r:gz') as stream:
        for member in stream:
            if member.isdir():continue
            name=member.name.removeprefix('./');total+=member.size
            if not member.isfile() or name.startswith('/') or '..' in Path(name).parts or name in hashes or total>2*1024**3 or len(hashes)>10000:
                raise ValueError('Unsafe or oversized evidence archive; preserve originals')
            digest=hashlib.sha256()
            with stream.extractfile(member) as file:
                for part in iter(lambda:file.read(1024**2),b''):digest.update(part)
            hashes[name]=digest.hexdigest()
            if name=='hashes.json':original_hashes=json.load(stream.extractfile(member))
    if original_hashes!={name:value for name,value in hashes.items() if name!='hashes.json'}:
        raise ValueError('Collected bytes differ from the guest original hash manifest')
    write(directory/'collection.json',dict(archive_sha256=sha(archive),uncompressed_bytes=total,files_sha256=hashes,
        scope='Transport integrity only; independent scientific audit follows deallocation'))


def recover_previous(ssh,directory,policy):
    destination=directory/'recovered-previous';destination.mkdir(mode=0o700)
    archive=destination/'originals.tar.gz'
    with archive.open('xb') as out:
        previous=policy.get('previous_window','hdsc-eval-1010a')
        if previous not in ('hdsc-eval-1010a','hdsc-eval-1010b'):raise ValueError('Unreviewed recovery directory')
        subprocess.run(ssh+['sudo -n python3 - --window '+previous],input=(ROOT/'scripts/hdsc-recovery.py').read_bytes(),
            stdout=out,stderr=subprocess.PIPE,check=True,timeout=120)
    verify_archive(archive,destination)
    with tarfile.open(archive,'r:gz') as stream:
        old_plan=stream.extractfile('previous-plan.json').read()
        with stream.extractfile('originals/data/core/jobs.jsonl') as file:
            prefix=b''.join(file.readline() for _ in range(policy['captured_prefix_rows']))
    if hashlib.sha256(old_plan).hexdigest()!=policy['previous_plan_sha256'] or hashlib.sha256(prefix).hexdigest()!=policy['captured_prefix_sha256']:
        raise ValueError('Recovered previous evidence disagrees with preserved plan/snapshot')
    write(destination/'provenance.json',dict(previous_plan_and_captured_prefix_verified=True,
        previous_results_pooled=False,originals_modified=False))


@contextmanager
def allocated_window(directory):
    # The cleanup applies even if start returns an error after Azure accepted it.
    write(directory/'start-request.json',{'utc':datetime.now(timezone.utc).isoformat()})
    try:
        az('vm','start','--ids',retained.VM,'--no-wait')
        yield
    finally:
        az('vm','deallocate','--ids',retained.VM,'--no-wait')
        deadline=time.monotonic()+180
        while True:
            vm=az('vm','get-instance-view','--ids',retained.VM)
            if 'PowerState/deallocated' in [r['code'] for r in vm['instanceView']['statuses']]:
                write(directory/'release.json',dict(utc=datetime.now(timezone.utc).isoformat(),power_state='PowerState/deallocated',
                    disk_retained=True,resources_destroyed=0));break
            if time.monotonic()>deadline:raise RuntimeError('Deallocation not confirmed; independent expiry remains armed')
            time.sleep(5)


def execute(args):
    plan=json.loads((args.directory/'plan.json').read_text());digest=sha(args.directory/'plan.json')
    approval(plan,json.loads(args.approval.read_text()),digest,datetime.now(timezone.utc))
    write(args.directory/'execution-attempt.json',{'utc':datetime.now(timezone.utc).isoformat()})
    live=retained.inventory();definition=live['guard']['properties']['definition']
    if hashlib.sha256(json.dumps(definition,sort_keys=True).encode()).hexdigest()!=plan['guard_definition_sha256']:
        raise ValueError('Expiry guard changed since review')
    original=STATE/'work-sample-1009b';outputs=json.loads((original/'outputs.json').read_text())
    ssh=['ssh','-F','/dev/null','-i',str(original/'id_ed25519'),'-o','BatchMode=yes','-o','ConnectTimeout=5',
         '-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2',
         '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(STATE/'fixed-work-1010a/known_hosts'),
         'cccontract@'+outputs['ssh_address']['value']]
    auth=subprocess.run(['gh','auth','status','--show-token'],capture_output=True,timeout=15)
    match=re.search(r'Token:\s*(\S+)',(auth.stdout+auth.stderr).decode())
    if auth.returncode or not match:raise ValueError('Registry authentication unavailable; VM stays off')
    token=match.group(1)
    now=datetime.now(timezone.utc);host_end=now+timedelta(minutes=plan['max_minutes']-7);guard_end=now+timedelta(minutes=plan['max_minutes']-3)
    payload=bundle(args,plan,dict(explicit_user_approval=True,plan_sha256=digest,expires_utc=host_end.isoformat()))
    renewed=copy.deepcopy(definition)
    renewed['actions']['ExpiryGuard']['expression']['greaterOrEquals'][1]="@ticks('"+guard_end.strftime('%Y-%m-%dT%H:%M:%SZ')+"')"
    body=args.directory/'guard-update.json';write(body,retained.guard_update_body(live['guard'],renewed))
    az('rest','--method','put','--url','https://management.azure.com'+plan['guard_id']+'?api-version=2019-05-01','--body','@'+str(body))
    actual=az('resource','show','--ids',plan['guard_id'],'--api-version','2019-05-01');retained.validate_guard(actual)
    if actual['properties']['definition']!=renewed:raise ValueError('Expiry readback mismatch; VM stays off')
    for key in ('id','identity','location','tags'):
        if actual.get(key)!=live['guard'].get(key):raise ValueError('Guard identity changed; VM stays off')
    write(args.directory/'renewed-guard.json',actual);retained.inventory()
    remote='/home/cccontract/cc-hdsc-'+args.directory.name
    with allocated_window(args.directory):
        deadline=time.monotonic()+480
        while subprocess.run(ssh+['true'],capture_output=True,timeout=10).returncode:
            if time.monotonic()>deadline:raise RuntimeError('SSH unavailable; deallocate before diagnosis')
            time.sleep(5)
        if plan.get('resumption'):recover_previous(ssh,args.directory,plan['resumption'])
        login=subprocess.run(ssh+['sudo -n install -d -m 700 /run/cc-hdsc-registry && sudo -n docker --config /run/cc-hdsc-registry login ghcr.io -u ihsenalaya --password-stdin'],input=(token+'\n').encode(),capture_output=True,timeout=30)
        token=None
        if login.returncode:raise RuntimeError('Registry login failed')
        with payload.open('rb') as source:
            subprocess.run(ssh+['umask 022; mkdir '+shlex.quote(remote)+' && tar -xf - -C '+shlex.quote(remote)],stdin=source,capture_output=True,timeout=120,check=True)
        limit=max(1,int((host_end-datetime.now(timezone.utc)).total_seconds()))
        with (args.directory/'host.stdout').open('xb') as out,(args.directory/'host.stderr').open('xb') as err:
            result=subprocess.run(ssh+['bash '+shlex.quote(remote+'/run-hdsc-host.sh')+' '+shlex.quote(remote)],stdout=out,stderr=err,timeout=limit+20)
        write(args.directory/'guest-exit.json',{'returncode':result.returncode,'utc':datetime.now(timezone.utc).isoformat()})
        # Technical failure: release immediately; partial evidence remains on retained disk.
        if result.returncode:raise RuntimeError('Guest failure: stop now; originals retained on VM disk for approved recovery')
        collect(ssh,remote,args.directory)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('review','run'))
    p.add_argument('--directory',type=Path,required=True);p.add_argument('--qualification',type=Path)
    p.add_argument('--approval',type=Path);p.add_argument('--model',type=Path)
    p.add_argument('--ai-only',action='store_true',help='Review only the remaining AI section plus its development gate')
    args=p.parse_args();os.umask(0o077)
    if not re.fullmatch(r'[a-z0-9-]{3,48}',args.directory.name):p.error('Use a new simple window directory name')
    if args.action=='review':
        if args.qualification is None:p.error('Qualification manifest required')
        review(args)
    else:
        if args.approval is None or args.model is None:p.error('Fresh approval and verified offline model required')
        execute(args)


if __name__=='__main__':main()
