"""Temporary Azure E0 window. Plan is read-only; mutation requires approved hash.

Approvals come from the user, never from this program. Expiry deallocates independently.
Private keys, plans, state, attestation and logs remain in Linux user state storage.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shlex
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "infrastructure/azure/gpu-window"
STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "cc-contract"
STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
os.umask(0o077)
ARCHIVE_DOWNLOAD_BYTE_LIMIT=8*1024**3
ARCHIVE_DOWNLOAD_TIMEOUT_SECONDS=480


def command(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def az_json(*args):
    raw = subprocess.check_output(["az", *args, "-o", "json", "--only-show-errors"], timeout=180)
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Windows Azure CLI emits the active Windows code page, unlike WSL UTF-8.
        decoded = raw.decode("cp1252")
    return json.loads(decoded)


def tf(*args, **kwargs):
    return command(["terraform", f"-chdir={MODULE}", *args], **kwargs)


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def record_phase(directory, phase, state, **details):
    event={'timestamp_utc':datetime.now(timezone.utc).isoformat(),
           'monotonic_ns':time.monotonic_ns(),'phase':phase,'state':state,**details}
    with (directory/'run-phases.jsonl').open('a') as output:
        output.write(json.dumps(event,separators=(',',':'))+'\n')
        output.flush();os.fsync(output.fileno())


def run_phase(directory, phase, args):
    started=time.monotonic()
    record_phase(directory,phase,'STARTED')
    try:
        command(args)
    except BaseException as error:
        record_phase(directory,phase,'FAILED',elapsed_seconds=time.monotonic()-started,
                     error_type=type(error).__name__)
        raise
    record_phase(directory,phase,'FINISHED',elapsed_seconds=time.monotonic()-started)


def verify_workload_plan(directory):
    bound=json.loads((directory/'inputs.json').read_text())
    expected=bool(bound.get('workload_sha256') or (directory/'workload-bundle.json').exists()
                  or (directory/'approved-workload-plan.json').exists())
    if not expected:return None
    if not (directory/'approved-workload-plan.json').is_file() or not (directory/'workload-bundle.json').is_file():
        raise ValueError('Required workload approval bindings missing; no provisioning allowed')
    scope=json.loads((directory/'approved-workload-plan.json').read_text())
    if scope['workload_bundle_sha256']!=sha(directory/'workload-bundle.json') or scope['host_script_sha256']!=sha(ROOT/'scripts/qualify-host.sh'):
        raise ValueError('Planned workload or host script changed; create a new reviewable plan')
    bundle=verify_bundle(directory/'workload-bundle.json')
    if bound['workload_sha256']!=scope['workload_bundle_sha256'] or bound['host_script_sha256']!=scope['host_script_sha256']:
        raise ValueError('Workload scope differs from planned inputs')
    # Read the actual saved binary plan, rather than trusting editable metadata
    # to assert what Terraform is about to provision.
    saved=json.loads(subprocess.check_output(['terraform',f'-chdir={MODULE}',
        'show','-json',str(directory/'plan.tfplan')],text=True))
    for variable,field in (('workload_sha256','workload_bundle_sha256'),('host_script_sha256','host_script_sha256')):
        if saved['variables'][variable]['value']!=scope[field]:
            raise ValueError('Saved Terraform plan workload bindings differ')
    if any(saved['variables'].get(name,{}).get('value')!=value for name,value in bound.items()):
        raise ValueError('Saved Terraform plan inputs, identity or expiry differ')
    return bundle


def preserve_applied_identity(directory):
    # Cleanup empties Terraform state. Save the actual VM UUID before workloads
    # so CPU attestation remains verifiable after the temporary VM is destroyed.
    data=(directory/'terraform.tfstate').read_bytes()
    state=json.loads(data)
    rows=[r for r in state.get('resources',[]) if r['type']=='azurerm_linux_virtual_machine' and r['name']=='gpu']
    if len(rows)!=1 or len(rows[0]['instances'])!=1 or not re.fullmatch(r'[a-f0-9-]{36}',rows[0]['instances'][0]['attributes']['virtual_machine_id']):
        raise ValueError('Applied GPU identity missing; preserve state and stop compute')
    with (directory/'tfstate-after-apply.json').open('xb') as output:output.write(data)
    with (directory/'vm-identity.json').open('x') as output:json.dump(rows,output,indent=2)


def verify_bundle(path, check_archive=True):
    bundle=json.loads(path.read_text())
    if bundle.get('transport')=='FIXED_WORK_IR_CAMPAIGN':
        # This distinct protocol uses the reserved 20-block order. A pilot
        # receipt cannot authorize a 140-job run or substitute for its gates.
        import importlib.util
        sys.path.insert(0,str(ROOT/'src'))
        script=ROOT/'scripts/run-fixed-work-campaign.py'
        loader=importlib.util.spec_from_file_location('fixed_work_cloud_guard',script)
        harness=importlib.util.module_from_spec(loader);loader.loader.exec_module(harness)
        if (bundle.get('schema_version')!=3 or
                re.fullmatch(r'[a-z0-9][a-z0-9-]{2,20}',bundle.get('campaign_id','')) is None or
                set(bundle.get('images',{}))!={'cuda','ir'} or
                bundle.get('planned_jobs')!=140 or bundle.get('selected_cases_per_job')!=100 or
                bundle.get('gpu_jobs_parallel') is not False or
                bundle.get('model_download_required') is not False or
                bundle.get('archive_download_byte_limit')!=ARCHIVE_DOWNLOAD_BYTE_LIMIT):
            raise ValueError('Fixed-work campaign scope or bounded transport differs')
        for kind,reference in bundle['images'].items():
            if re.fullmatch(r'ghcr.io/ihsenalaya/cc-contract-'+kind+r'@sha256:[a-f0-9]{64}',reference) is None:
                raise ValueError('Fixed-work image must be an immutable project digest')
        sources={'campaign_harness':script,'helper_harness':ROOT/'scripts/run-work-sample.py'}
        for name in ('campaign_spec','protocol','reserved_schedule','cpu_kind_receipt',
                     'independent_cpu_review','local_qualification'):
            if not bundle.get(name+'_path') or not bundle.get(name+'_sha256'):
                raise ValueError('Missing fixed-work binding: '+name)
            sources[name]=Path(bundle[name+'_path'])
        for name,source in sources.items():
            if source.is_symlink() or sha(source)!=bundle.get(name+'_sha256'):
                raise ValueError('Fixed-work qualified source changed: '+name)
        spec=json.loads(sources['campaign_spec'].read_text())
        if (spec!=harness.make_spec('cuda') or spec['image_digest']!=bundle['images']['ir'] or
                spec['protocol_sha256']!=bundle['protocol_sha256'] or
                spec['reserved_schedule_sha256']!=bundle['reserved_schedule_sha256'] or
                spec['shared_harness_sha256']!=bundle['helper_harness_sha256']):
            raise ValueError('Fixed-work spec, protocol or source differs')
        # Delegate the complete original CPU archive/independent semantic review
        # checks to the same preparation guard; hash bindings alone are not gates.
        loader=importlib.util.spec_from_file_location('fixed_work_bundle_guard',ROOT/'scripts/prepare-fixed-work-campaign.py')
        guard=importlib.util.module_from_spec(loader);loader.loader.exec_module(guard)
        if check_archive:
            guard.verify_local_gates(bundle)
        return bundle
    finite_work=bundle.get('transport')=='FINITE_WORK_IR_SAMPLE'
    sample=bundle.get('transport') in ('SEQUENTIAL_IR_SAMPLE','FINITE_WORK_IR_SAMPLE')
    sample_script='run-work-sample.py' if finite_work else 'run-sequential-sample.py'
    kinds=('cuda','ir') if sample else ('cuda','ir','torch')
    if sample and set(bundle['images'])!=set(kinds):
        raise ValueError('Sequential sample may pull only CUDA and IR images')
    for kind in kinds:
        if not re.fullmatch(r'ghcr.io/ihsenalaya/cc-contract-'+kind+r'@sha256:[a-f0-9]{64}',bundle['images'][kind]):
            raise ValueError('Bundle image must be an immutable project digest')
    if sample:
        if sha(ROOT/'scripts'/sample_script)!=bundle['sample_harness_sha256']:
            raise ValueError('Planned sequential harness changed')
        spec_path=Path(bundle['sample_spec_path'])
        if sha(spec_path)!=bundle['sample_spec_sha256']:
            raise ValueError('Planned sequential specification changed')
        spec=json.loads(spec_path.read_text())
        if spec['image_digest']!=bundle['images']['ir'] or spec['harness_sha256']!=bundle['sample_harness_sha256']:
            raise ValueError('Sequential sample image/harness differs from specification')
        # The harness validates the exact development-only schedule again before
        # creating a CUDA context. These guards also bind it before provisioning.
        if spec['backend']!='cuda' or spec['confirmatory'] is not False or spec['comparison_schedule_changed'] is not False:
            raise ValueError('Sequential sample must remain a nonconfirmatory development pilot')
        import importlib.util
        sys.path.insert(0,str(ROOT/'src'))
        module_spec=importlib.util.spec_from_file_location('sequential_sample_guard',ROOT/'scripts'/sample_script)
        harness=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(harness)
        if spec!=harness.make_spec('cuda'):
            raise ValueError('Sequential sample schedule, limits or provenance changed')
        if finite_work:
            # Retain the exact local gates reviewed before approving this window.
            for name in ('cpu_kind_receipt','independent_cpu_review','volume_preflight',
                         'volume_preflight_source_binding'):
                if not bundle.get(name+'_path') or not bundle.get(name+'_sha256'):
                    raise ValueError('Finite-work local gate binding missing: '+name)
                if sha(Path(bundle[name+'_path']))!=bundle[name+'_sha256']:
                    raise ValueError('Finite-work local gate changed: '+name)
        return bundle
    if bundle.get('transport')=='AZURE_BLOB_IMDS':
        sys.path.insert(0,str(ROOT/'src'))
        from cc_contract.cloud_model import validate_spec
        cloud=validate_spec(bundle['model_cloud'])
        if not re.fullmatch(r'ghcr.io/ihsenalaya/cc-contract-cpu@sha256:[a-f0-9]{64}',bundle['cloud_transport_image']):
            raise ValueError('Cloud transport image must be an immutable project digest')
        if sha(ROOT/'src/cc_contract/cloud_model.py')!=bundle['cloud_downloader_sha256']:
            raise ValueError('Planned cloud downloader changed')
        rows={r['name']:r for r in cloud['files']}
        if rows['cc-model-manifest.json']['sha256']!=bundle['model_manifest_sha256'] or rows['inference-corpus.json']['sha256']!=bundle['corpus_sha256']:
            raise ValueError('Cloud model manifest/corpus changed')
        if len(rows)!=14 or sum(name.endswith('.safetensors') for name in rows)!=4:
            raise ValueError('Cloud model shard set incomplete')
    elif check_archive:
        if bundle.get('transport')=='DETERMINISTIC_TAR_STREAM':
            directory=Path(bundle['model_directory']);manifest=directory/'cc-model-manifest.json'
            if sha(manifest)!=bundle['model_manifest_sha256'] or sha(Path(bundle['corpus_path']))!=bundle['corpus_sha256']:
                raise ValueError('Prepared model manifest/corpus changed')
            for name,expected in json.loads(manifest.read_text())['file_sha256'].items():
                file=directory/name
                if Path(name).name!=name or file.is_symlink() or sha(file)!=expected:
                    raise ValueError('Prepared model data changed')
        elif sha(Path(bundle['model_archive']))!=bundle['model_archive_sha256']:
            raise ValueError('Prepared model archive hash mismatch')
    if bundle['corpus_filename']!='inference-corpus.json' or bundle['model_revision']!='a09a35458c702b33eeacc393d103063234e8bc28':
        raise ValueError('Unqualified model/corpus bundle')
    return bundle


def ensure_window(directory):
    inputs = json.loads((directory / "inputs.json").read_text())
    expected = "cc-contract-" + inputs["window_id"]
    outputs = json.loads((directory / "outputs.json").read_text())
    group = outputs["resource_group"]["value"]
    vm_id = outputs["vm_id"]["value"]
    assert group == expected
    assert vm_id.lower() == f'/subscriptions/{inputs["subscription_id"]}/resourcegroups/{expected}/providers/microsoft.compute/virtualmachines/{expected}'.lower()
    vm = az_json("vm", "show", "--ids", vm_id)
    assert vm["tags"]["project"] == "cc-contract" and vm["tags"]["window"] == inputs["window_id"]
    return inputs, outputs


def ssh_args(directory, outputs):
    return ["ssh", "-F", "/dev/null", "-i", str(directory / "id_ed25519"), "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={directory / 'known_hosts'}", "cccontract@" + outputs["ssh_address"]["value"]]


def remote_evidence_directory(directory):
    """Keep a resumed campaign separate from all originals on the retained disk."""
    bundle_path=directory/'workload-bundle.json'
    if bundle_path.is_file():
        bundle=json.loads(bundle_path.read_text())
        if bundle.get('transport')=='FIXED_WORK_IR_CAMPAIGN':
            identity=bundle.get('campaign_id','')
            if re.fullmatch(r'[a-z0-9][a-z0-9-]{2,20}',identity) is None or identity!=directory.name:
                raise ValueError('Remote evidence identity differs from new campaign')
            return '/home/cccontract/cc-campaigns/'+identity+'/cc-contract-evidence'
    return '/home/cccontract/cc-contract-evidence'


def download_evidence(directory, outputs, path):
    root=remote_evidence_directory(directory)
    arguments=ssh_args(directory,outputs)+['tar','-czf','-','-C',str(PurePosixPath(root).parent),'cc-contract-evidence']
    bundle_path=directory/'workload-bundle.json'
    bundle=json.loads(bundle_path.read_text()) if bundle_path.is_file() else {}
    if bundle.get('transport')!='FIXED_WORK_IR_CAMPAIGN':
        with path.open('xb') as stream:
            subprocess.run(arguments,stdout=stream,check=True)
        return
    limit=bundle.get('archive_download_byte_limit')
    if limit!=ARCHIVE_DOWNLOAD_BYTE_LIMIT:
        raise ValueError('Approved bounded archive download required')
    arguments=ssh_args(directory,outputs)+['set -o pipefail; tar -cf - -C '+
        shlex.quote(str(PurePosixPath(root).parent))+' cc-contract-evidence | gzip -1']
    # Stop the producer at the byte bound; originals remain on the retained disk.
    # Deadline is also bounded by the independent Azure expiry on this window.
    with path.open('xb') as stream, (directory/'evidence-transfer.stderr').open('xb') as errors:
        producer=subprocess.Popen(arguments,stdout=subprocess.PIPE,stderr=errors)
        size=0
        try:
            deadline=time.monotonic()+ARCHIVE_DOWNLOAD_TIMEOUT_SECONDS
            with selectors.DefaultSelector() as selector:
                selector.register(producer.stdout,selectors.EVENT_READ)
                while True:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:
                        raise TimeoutError('Evidence export exceeded eight-minute deadline')
                    if not selector.select(timeout=min(10,remaining)):continue
                    chunk=os.read(producer.stdout.fileno(),8*1024*1024)
                    if not chunk:break
                    if size+len(chunk)>limit:
                        raise ValueError('Compressed evidence download exceeds approved byte bound')
                    stream.write(chunk);size+=len(chunk)
            stream.flush();os.fsync(stream.fileno())
            if producer.wait(timeout=30)!=0:
                raise RuntimeError('Original guest evidence export failed')
        finally:
            if producer.poll() is None:producer.kill();producer.wait(timeout=30)
            producer.stdout.close()


def release(directory):
    _, outputs = ensure_window(directory)
    vm_id = outputs["vm_id"]["value"]
    command(["az", "vm", "deallocate", "--ids", vm_id, "--only-show-errors"])
    state = az_json("vm", "get-instance-view", "--ids", vm_id)
    codes = [s["code"] for s in state["instanceView"]["statuses"]]
    if "PowerState/deallocated" not in codes:
        raise RuntimeError("deallocation state not confirmed; inspect private logs and cloud expiry")
    receipt = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "power_state": "PowerState/deallocated", "retained_os_disk": True}
    (directory / "release.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


def verify_evidence_archive(path):
    """Hash originals in one forward gzip pass with bounded metadata memory.

    File data is read in 8 MiB chunks. At most 10,000 archive entries, 4 KiB
    path names, and a 2 MiB root SHA256SUMS manifest are retained. No archive
    pathname is extracted to the local filesystem, and manifest order need not
    match TAR order. Links and any incomplete hash inventory fail closed.
    """
    import tarfile
    root = 'cc-contract-evidence'
    manifest_name = root + '/SHA256SUMS'
    names, files, manifest = set(), {}, None

    def safe_name(value):
        if (not isinstance(value, str) or not value or len(value.encode()) > 4096
                or value.startswith('/') or '\\' in value
                or any(ord(character) < 32 for character in value)):
            raise ValueError('Unsafe evidence archive path')
        normalized = value.rstrip('/')
        parts = normalized.split('/')
        if any(part in ('', '.', '..') for part in parts) or PurePosixPath(normalized).parts[0] != root:
            raise ValueError('Unsafe evidence archive path')
        return normalized

    with tarfile.open(path, mode='r|gz') as archive:
        for member in archive:
            name = safe_name(member.name)
            if name in names:
                raise ValueError('Duplicate evidence archive entry')
            names.add(name)
            if len(names) > 10000:
                raise ValueError('Evidence archive entry count exceeds metadata bound')
            if not (member.isdir() or member.isfile()):
                raise ValueError('Evidence archive links and special entries are forbidden')
            if member.isdir():
                continue
            if member.size < 0:
                raise ValueError('Invalid evidence file size')
            if name == manifest_name:
                if member.size > 2 * 1024 * 1024:
                    raise ValueError('Evidence hash manifest exceeds metadata bound')
                with archive.extractfile(member) as stream:
                    manifest = stream.read(2 * 1024 * 1024 + 1)
                if len(manifest) != member.size:
                    raise ValueError('Truncated evidence hash manifest')
                continue
            digest, size = hashlib.sha256(), 0
            with archive.extractfile(member) as stream:
                for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                    digest.update(chunk)
                    size += len(chunk)
            if size != member.size:
                raise ValueError('Truncated original evidence file')
            files[name] = digest.hexdigest()
    if manifest is None:
        raise ValueError('Missing root evidence hash manifest')
    expected = {}
    for line in manifest.decode('utf-8').splitlines():
        if re.fullmatch(r'[a-f0-9]{64}  \./[^\n]+', line) is None:
            raise ValueError('Malformed original evidence hash record')
        digest, relative = line.split('  ', 1)
        name = safe_name(root + '/' + relative[2:])
        if name in expected:
            raise ValueError('Duplicate original evidence hash record')
        expected[name] = digest
    if set(expected) != set(files):
        raise ValueError('Original evidence hash inventory is incomplete or contains unlisted files')
    if any(files[name] != digest for name, digest in expected.items()):
        raise ValueError('Original evidence file hash mismatch')
    return len(files)


def collect_and_release(directory):
    _, outputs = ensure_window(directory)
    if (directory / "collection.json").exists():
        receipt = json.loads((directory / "collection.json").read_text())
        assert receipt["archive_sha256"] == sha(directory / receipt["archive_file"])
        release(directory)
        return
    path = directory / ("guest-evidence-" + uuid4().hex + ".tar.gz")
    try:
        download_evidence(directory,outputs,path)
        verified_files = verify_evidence_archive(path)
        receipt = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "archive_sha256": sha(path), "archive_file": path.name, "files_verified": verified_files, "scope": "E0_REAL_HOST_EVIDENCE_REQUIRES_REVIEW", "archive_verification": "ONE_PASS_STREAMING_TAR_GZIP_COMPLETE_HASH_INVENTORY", "remote_evidence_directory":remote_evidence_directory(directory)}
        (directory / "collection.json").write_text(json.dumps(receipt, indent=2) + "\n")
    finally:
        # Even export failure must stop compute: evidence remains on persistent OS disk.
        release(directory)


def main():
    # Prefer the qualified Linux client over the unreliable WSL/Windows relay.
    native = STATE / 'azure-native-cli-venv/bin/az'
    config = STATE / 'azure-native-cli-config'
    if native.is_file() and (config / 'azureProfile.json').is_file():
        os.environ['PATH'] = str(native.parent) + os.pathsep + os.environ['PATH']
        os.environ['AZURE_CONFIG_DIR'] = str(config)
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["plan", "run", "apply", "qualify", "collect-release", "release", "destroy"])
    p.add_argument("--window", required=True)
    p.add_argument("--ssh-source-cidr")
    p.add_argument("--approved-plan-sha256")
    p.add_argument('--confirm-destroy',action='store_true',
                   help='Explicit user-approved deletion of retained temporary resources')
    p.add_argument('--workload-bundle',type=Path)
    p.add_argument('--max-window-minutes',type=int,choices=(60,90,120),default=120,
                   help='Absolute expiry from planning; does not extend on apply')
    args = p.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,20}", args.window):
        p.error("use a unique lowercase window name")
    directory = STATE / args.window
    directory.mkdir(exist_ok=True, mode=0o700)
    if args.action == "run":
        # Export evidence and deallocate compute; retain disks and infrastructure
        # until the user explicitly decides whether to resume or destroy them.
        if args.approved_plan_sha256 != sha(directory / "plan.tfplan"):
            p.error("explicit user-approved matching plan hash required")
        child = [sys.executable, str(Path(__file__).resolve())]
        started=time.monotonic()
        run_start={'timestamp_utc':datetime.now(timezone.utc).isoformat(),
                   'scope':'APPLY_QUALIFICATION_SAMPLE_EXPORT_AND_DEALLOCATION_KEEP_RESOURCES',
                   'plan_sha256':args.approved_plan_sha256}
        with (directory/'run-start.json').open('x') as output:
            json.dump(run_start,output,indent=2);output.write('\n')
        failure=None
        try:
            run_phase(directory,'apply',child + ["apply", "--window", args.window, "--approved-plan-sha256", args.approved_plan_sha256])
            run_phase(directory,'qualify_collect_release',child + ["qualify", "--window", args.window])
        except BaseException as error:
            failure=type(error).__name__
            raise
        finally:
            if not (directory / "collection.json").exists():
                print("Evidence export unverified: any allocated compute is released by recovery/expiry; temporary resources are preserved. Inspect private logs.", file=sys.stderr)
            result={'started_at_utc':run_start['timestamp_utc'],
                    'finished_at_utc':datetime.now(timezone.utc).isoformat(),
                    'elapsed_seconds':time.monotonic()-started,'error_type':failure,
                    'scope':run_start['scope'],
                    'temporary_resources_retained_for_user_decision':True,
                    'resources_destroyed_automatically':False,
                    'analysis_and_user_decision_time_included':False}
            with (directory/'run-exit.json').open('x') as output:
                json.dump(result,output,indent=2);output.write('\n')
    elif args.action == "plan":
        if not args.ssh_source_cidr:
            p.error("--ssh-source-cidr is required for planning")
        if (directory / "inputs.json").exists():
            p.error("window already planned; choose a new identifier to preserve provenance")
        if args.workload_bundle:
            verify_bundle(args.workload_bundle)
            (directory/'workload-bundle.json').write_bytes(args.workload_bundle.read_bytes())
            (directory/'workload-sha256').write_text(sha(directory/'workload-bundle.json'))
        # Public key only enters Terraform. Private key stays off the Windows workspace.
        command(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(directory / "id_ed25519")])
        account = az_json("account", "show")
        inputs = {"subscription_id": account["id"], "window_id": args.window, "ssh_public_key": (directory / "id_ed25519.pub").read_text().strip(), "ssh_source_cidr": args.ssh_source_cidr, "expires_at_utc": (datetime.now(timezone.utc) + timedelta(minutes=args.max_window_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if args.workload_bundle:
            inputs['workload_sha256']=sha(directory/'workload-bundle.json')
            inputs['host_script_sha256']=sha(ROOT/'scripts/qualify-host.sh')
            bundle=verify_bundle(directory/'workload-bundle.json')
            if bundle.get('transport')=='AZURE_BLOB_IMDS':inputs['model_container_scope']=bundle['model_cloud']['resource_scope']
        (directory / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
        with (directory / "plan.log").open("w") as log:
            tf("init", "-input=false", "-reconfigure", f"-backend-config=path={directory / 'terraform.tfstate'}", stdout=log, stderr=subprocess.STDOUT)
            tf("plan", "-input=false", f"-var-file={directory / 'inputs.json'}", f"-out={directory / 'plan.tfplan'}", stdout=log, stderr=subprocess.STDOUT)
        plan = json.loads(subprocess.check_output(["terraform", f"-chdir={MODULE}", "show", "-json", str(directory / "plan.tfplan")], text=True))
        changes = [{"address": r["address"], "actions": r["change"]["actions"]} for r in plan["resource_changes"]]
        assert all(c["actions"] in [["create"], ["no-op"]] for c in changes)
        assert sum(c["address"] == "azurerm_linux_virtual_machine.gpu" for c in changes) == 1
        (directory / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
        summary = {"window": args.window, "planned_resources": changes, "plan_sha256": sha(directory / "plan.tfplan"), "expires_at_utc": inputs["expires_at_utc"], "approval_required": True, "created_resources": 0}
        if (directory/'workload-bundle.json').exists():
            summary['workload_bundle_sha256']=sha(directory/'workload-bundle.json')
            summary['host_script_sha256']=sha(ROOT/'scripts/qualify-host.sh')
            (directory/'approved-workload-plan.json').write_text(json.dumps(summary,indent=2)+'\n')
        (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
    elif args.action == "apply":
        if args.approved_plan_sha256 != sha(directory / "plan.tfplan"):
            p.error("explicit user-approved matching plan hash required")
        bundle=verify_workload_plan(directory)
        expiry = datetime.fromisoformat(json.loads((directory / "inputs.json").read_text())["expires_at_utc"].replace("Z", "+00:00"))
        minimum_minutes=(80 if bundle and bundle.get('transport')=='FINITE_WORK_IR_SAMPLE' else
                         75 if bundle and bundle.get('transport')=='SEQUENTIAL_IR_SAMPLE' else 45)
        if expiry - datetime.now(timezone.utc) < timedelta(minutes=minimum_minutes):
            p.error("expiry too close; prepare a new plan and obtain approval")
        # If provisioning fails partway, independently-created cloud expiry still applies.
        with (directory / "apply.log").open("w") as log:
            tf("init", "-input=false", "-reconfigure", f"-backend-config=path={directory / 'terraform.tfstate'}", stdout=log, stderr=subprocess.STDOUT)
            try:
                tf("apply", "-input=false", str(directory / "plan.tfplan"), stdout=log, stderr=subprocess.STDOUT)
            except BaseException:
                # Stop any partially provisioned matching GPU; preserve its persistent disk.
                inputs = json.loads((directory / "inputs.json").read_text())
                vm_id = f'/subscriptions/{inputs["subscription_id"]}/resourceGroups/cc-contract-{inputs["window_id"]}/providers/Microsoft.Compute/virtualMachines/cc-contract-{inputs["window_id"]}'
                try:
                    vm = az_json("vm", "show", "--ids", vm_id)
                    assert vm["tags"]["project"] == "cc-contract" and vm["tags"]["window"] == inputs["window_id"]
                    command(["az", "vm", "deallocate", "--ids", vm_id, "--only-show-errors"], stdout=log, stderr=subprocess.STDOUT)
                except Exception as recovery_error:
                    log.write("Partial provisioning recovery unresolved: " + type(recovery_error).__name__ + "; check independent expiry and preserved state.\n")
                raise
        output = subprocess.check_output(["terraform", f"-chdir={MODULE}", "output", "-json"], text=True)
        (directory / "outputs.json").write_text(output)
        try:
            ensure_window(directory)
            preserve_applied_identity(directory)
        except BaseException:
            release(directory)
            raise
        print("Approved temporary window provisioned; independent expiry configured. Begin immediate qualification.")
    elif args.action == "qualify":
        _, outputs = ensure_window(directory)
        evidence_root=remote_evidence_directory(directory)
        evidence_quote=shlex.quote(evidence_root)
        try:
            if (directory / "qualification-exit.json").exists() or (directory / "collection.json").exists():
                raise RuntimeError("Window already executed; preserve finalized evidence and use a new window")
            image = (ROOT / ".local/cuda/remote-digest").read_text().strip()
            assert re.fullmatch(r"ghcr.io/ihsenalaya/cc-contract-cuda@sha256:[a-f0-9]{64}", image)
            # The archive was verified before apply. The guest independently
            # hashes the bytes actually transferred, avoiding local rereading
            # of 14 GiB while GPU compute is allocated.
            bundle=verify_bundle(directory/'workload-bundle.json',check_archive=False) if (directory/'workload-bundle.json').exists() else None
            if bundle:
                scope=json.loads((directory/'approved-workload-plan.json').read_text())
                if scope['workload_bundle_sha256']!=sha(directory/'workload-bundle.json') or scope['host_script_sha256']!=sha(ROOT/'scripts/qualify-host.sh'):
                    raise RuntimeError('Qualification workload changed since plan approval')
            images=list(bundle['images'].values()) if bundle else [image]
            if bundle and bundle.get('transport')=='AZURE_BLOB_IMDS':images.append(bundle['cloud_transport_image'])
            if bundle:image=bundle['images']['cuda']
            # Credential stays in a root-only RAM directory and is removed after pull.
            credential_file = Path.home() / ".config/gh/hosts.yml"
            match = re.search(r"^\s+oauth_token:\s*(\S+)\s*$", credential_file.read_text(), re.M)
            if not match:
                raise RuntimeError("GHCR read credential unavailable")
            # Refuse to reuse an existing new campaign directory, including
            # partial evidence. A later resume must receive a new identity.
            fresh='test ! -e '+evidence_quote+'; ' if bundle and bundle.get('transport')=='FIXED_WORK_IR_CAMPAIGN' else ''
            pulls='; '.join('sudo docker --config /run/cc-contract-registry pull '+shlex.quote(ref)+' >> '+evidence_quote+'/image-pull.log 2>&1' for ref in images)
            remote = "set -e; "+fresh+"mkdir -p "+evidence_quote+"; sudo install -d -m 700 /run/cc-contract-registry; trap 'sudo rm -rf /run/cc-contract-registry' EXIT; sudo docker --config /run/cc-contract-registry login ghcr.io -u ihsenalaya --password-stdin > "+evidence_quote+"/registry-login.log 2>&1; "+pulls
            command(ssh_args(directory, outputs) + [remote], input=match.group(1) + "\n", timeout=600)
            arguments=[image]
            if bundle and bundle.get('transport') in ('SEQUENTIAL_IR_SAMPLE','FINITE_WORK_IR_SAMPLE','FIXED_WORK_IR_CAMPAIGN'):
                # Small, hash-bound scripts only. No Qwen download or Torch pull.
                finite_work=bundle['transport']=='FINITE_WORK_IR_SAMPLE'
                campaign=bundle['transport']=='FIXED_WORK_IR_CAMPAIGN'
                sample_script='run-fixed-work-campaign.py' if campaign else 'run-work-sample.py' if finite_work else 'run-sequential-sample.py'
                sample_root=evidence_root+'/sample-inputs'
                command(ssh_args(directory,outputs)+['mkdir -p '+shlex.quote(sample_root)],timeout=30)
                spec_key='campaign_spec' if campaign else 'sample_spec'
                harness_key='campaign_harness' if campaign else 'sample_harness'
                transfers=[('spec.json',Path(bundle[spec_key+'_path']),bundle[spec_key+'_sha256']),
                    (sample_script,ROOT/'scripts'/sample_script,bundle[harness_key+'_sha256'])]
                if campaign:
                    transfers += [('run-work-sample.py',ROOT/'scripts/run-work-sample.py',bundle['helper_harness_sha256']),
                        ('fixed-work-campaign-v0.3.md',Path(bundle['protocol_path']),bundle['protocol_sha256']),
                        ('comparison-schedule.json',Path(bundle['reserved_schedule_path']),bundle['reserved_schedule_sha256'])]
                for name,source,expected in transfers:
                    target=sample_root+'/'+name
                    remote='set -e; cat > '+shlex.quote(target)+'; printf "%s\\n" '+shlex.quote(expected+'  '+target)+' | sha256sum -c -; chmod 444 '+shlex.quote(target)
                    command(ssh_args(directory,outputs)+[remote],input=source.read_bytes().decode('utf-8'),timeout=60)
                arguments += [bundle['images']['ir'],'','','',sample_root+'/spec.json',sample_root+'/'+sample_script,bundle[spec_key+'_sha256'],bundle[harness_key+'_sha256']]
                if campaign:arguments += ['campaign',sample_root+'/run-work-sample.py',bundle['helper_harness_sha256']]
                elif finite_work:arguments.append('work')
            elif bundle:
                # Model bytes are already prepared and verified. Download directly
                # from the private Azure backup, or transfer the prepared archive.
                target='/home/cccontract/cc-contract-model'
                cloud=bundle.get('transport')=='AZURE_BLOB_IMDS'
                streaming=bundle.get('transport')=='DETERMINISTIC_TAR_STREAM'
                if cloud:
                    download='set -e; mkdir -p ~/cc-contract-evidence; sudo -n install -d -m 700 -o 10001 -g 10001 '+target+' ~/cc-contract-evidence/cloud-transfer; sudo -n docker run --rm -i --network host --read-only --cap-drop ALL --security-opt no-new-privileges --mount type=bind,source='+target+',target=/model --mount type=bind,source=/home/cccontract/cc-contract-evidence/cloud-transfer,target=/evidence --entrypoint python3 '+shlex.quote(bundle['cloud_transport_image'])+' -m cc_contract.cloud_model --manifest /dev/stdin --output /model --receipt /evidence/model-download.json > ~/cc-contract-evidence/model-download.stdout 2> ~/cc-contract-evidence/model-download.stderr'
                    command(ssh_args(directory,outputs)+[download],input=json.dumps(bundle['model_cloud']),timeout=900)
                else:
                    remote_archive='/home/cccontract/model-bundle.tar'+('' if streaming else '.gz')
                    transfer='set -e; cat > '+remote_archive+'; echo '+shlex.quote(bundle['model_archive_sha256']+'  '+remote_archive)+' | sha256sum -c -; mkdir -p '+target+'; tar --no-same-owner '+('-xf ' if streaming else '-xzf ')+remote_archive+' -C '+target+'; sudo chown -R 10001:10001 '+target
                if streaming:
                    with (directory/'model-stream.stderr').open('wb') as errors:
                        producer=subprocess.Popen([sys.executable,str(ROOT/'scripts/stream-model-bundle.py'),'--bundle',str(directory/'workload-bundle.json')],stdout=subprocess.PIPE,stderr=errors)
                        try:
                            subprocess.run(ssh_args(directory,outputs)+[transfer],stdin=producer.stdout,check=True,timeout=1800)
                            producer.stdout.close()
                            if producer.wait(timeout=30)!=0:raise RuntimeError('Local model stream did not match prepared hash')
                        finally:
                            if producer.poll() is None:producer.kill();producer.wait()
                            producer.stdout.close()
                elif not cloud:
                    with Path(bundle['model_archive']).open('rb') as stream:
                        subprocess.run(ssh_args(directory,outputs)+[transfer],stdin=stream,check=True,timeout=1800)
                arguments += [bundle['images']['ir'],bundle['images']['torch'],target,bundle['corpus_filename']]
            with (directory / "qualification-session.log").open("w") as log:
                qualification_timeout=3900 if bundle and bundle.get('transport')=='FIXED_WORK_IR_CAMPAIGN' else 2100 if bundle and bundle.get('transport')=='FINITE_WORK_IR_SAMPLE' else 1800
                result = subprocess.run(ssh_args(directory, outputs) + ['CC_EVIDENCE_DIRECTORY='+evidence_quote+" bash -s -- " + ' '.join(shlex.quote(value) for value in arguments)], input=(ROOT / "scripts/qualify-host.sh").read_text(), text=True, stdout=log, stderr=subprocess.STDOUT, timeout=qualification_timeout)
            (directory / "qualification-exit.json").write_text(json.dumps({"returncode": result.returncode, "timestamp_utc": datetime.now(timezone.utc).isoformat()}) + "\n")
            return result.returncode
        finally:
            try:
                # Hash partial pull/download failures as well as completed workloads.
                finalize="set -e; mkdir -p "+evidence_quote+"; cd "+evidence_quote+"; sudo -n chown -R $(id -u):$(id -g) .; find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS"
                command(ssh_args(directory,outputs)+[finalize],timeout=60)
            finally:
                collect_and_release(directory)
    elif args.action == "collect-release":
        collect_and_release(directory)
    elif args.action == "release":
        release(directory)
    elif args.action == "destroy":
        if not args.confirm_destroy:
            p.error('--confirm-destroy requires an explicit user decision to delete retained temporary resources')
        ensure_window(directory)
        assert (directory / "collection.json").exists(), "Verified evidence export required before destroying persistent disk"
        collection = json.loads((directory / "collection.json").read_text())
        assert collection["archive_sha256"] == sha(directory / collection["archive_file"])
        with (directory / "destroy.log").open("w") as log:
            tf("init", "-input=false", "-reconfigure", f"-backend-config=path={directory / 'terraform.tfstate'}", stdout=log, stderr=subprocess.STDOUT)
            tf("destroy", "-input=false", "-auto-approve", f"-var-file={directory / 'inputs.json'}", stdout=log, stderr=subprocess.STDOUT)
        outputs = json.loads((directory / "outputs.json").read_text())
        present = subprocess.check_output(["az", "group", "exists", "--name", outputs["resource_group"]["value"], "-o", "tsv"], text=True).strip()
        assert present.lower() == "false", "Resource group deletion not confirmed"
        print("Temporary resources destroyed; private verified archive retained.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
