"""Temporary Azure E0 window. Plan is read-only; mutation requires approved hash.

Approvals come from the user, never from this program. Expiry deallocates independently.
Private keys, plans, state, attestation and logs remain in Linux user state storage.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "infrastructure/azure/gpu-window"
STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "cc-contract"
STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
os.umask(0o077)


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
    for kind in ('cuda','ir','torch'):
        if not re.fullmatch(r'ghcr.io/ihsenalaya/cc-contract-'+kind+r'@sha256:[a-f0-9]{64}',bundle['images'][kind]):
            raise ValueError('Bundle image must be an immutable project digest')
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
    return ["ssh", "-F", "/dev/null", "-i", str(directory / "id_ed25519"), "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={directory / 'known_hosts'}", "cccontract@" + outputs["ssh_address"]["value"]]


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


def collect_and_release(directory):
    _, outputs = ensure_window(directory)
    if (directory / "collection.json").exists():
        receipt = json.loads((directory / "collection.json").read_text())
        assert receipt["archive_sha256"] == sha(directory / receipt["archive_file"])
        release(directory)
        return
    path = directory / ("guest-evidence-" + uuid4().hex + ".tar.gz")
    try:
        with path.open("wb") as stream:
            subprocess.run(ssh_args(directory, outputs) + ["tar", "-czf", "-", "-C", "/home/cccontract", "cc-contract-evidence"], stdout=stream, check=True)
        # Inspect archive safely without unpacking remote pathnames on the host.
        import tarfile
        with tarfile.open(path) as archive:
            names = archive.getnames()
            assert names and all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in names)
            manifests = [m for m in archive.getmembers() if m.name.endswith("/SHA256SUMS")]
            assert len(manifests) == 1
            lines = archive.extractfile(manifests[0]).read().decode().splitlines()
            base = str(Path(manifests[0].name).parent)
            for line in lines:
                expected, name = line.split(maxsplit=1)
                candidate = base + "/" + name.removeprefix("./")
                assert hashlib.sha256(archive.extractfile(candidate).read()).hexdigest() == expected
        receipt = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "archive_sha256": sha(path), "archive_file": path.name, "files_verified": len(lines), "scope": "E0_REAL_HOST_EVIDENCE_REQUIRES_REVIEW"}
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
    p.add_argument('--workload-bundle',type=Path)
    args = p.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,20}", args.window):
        p.error("use a unique lowercase window name")
    directory = STATE / args.window
    directory.mkdir(exist_ok=True, mode=0o700)
    if args.action == "run":
        # One approved command drives the entire cycle, including cleanup on failure.
        if args.approved_plan_sha256 != sha(directory / "plan.tfplan"):
            p.error("explicit user-approved matching plan hash required")
        child = [sys.executable, str(Path(__file__).resolve())]
        try:
            command(child + ["apply", "--window", args.window, "--approved-plan-sha256", args.approved_plan_sha256])
            command(child + ["qualify", "--window", args.window])
        finally:
            if (directory / "collection.json").exists():
                command(child + ["destroy", "--window", args.window])
            else:
                print("Evidence export unverified: any allocated compute is released by recovery/expiry; persistent disk is preserved. Inspect private logs.", file=sys.stderr)
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
        inputs = {"subscription_id": account["id"], "window_id": args.window, "ssh_public_key": (directory / "id_ed25519.pub").read_text().strip(), "ssh_source_cidr": args.ssh_source_cidr, "expires_at_utc": (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
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
        if (directory/'approved-workload-plan.json').exists():
            scope=json.loads((directory/'approved-workload-plan.json').read_text())
            if scope['workload_bundle_sha256']!=sha(directory/'workload-bundle.json') or scope['host_script_sha256']!=sha(ROOT/'scripts/qualify-host.sh'):
                p.error('Planned workload or host script changed; create a new reviewable plan')
            verify_bundle(directory/'workload-bundle.json')
            bound=json.loads((directory/'inputs.json').read_text())
            if bound['workload_sha256']!=scope['workload_bundle_sha256'] or bound['host_script_sha256']!=scope['host_script_sha256']:
                p.error('Workload scope is not bound to Terraform plan inputs')
        expiry = datetime.fromisoformat(json.loads((directory / "inputs.json").read_text())["expires_at_utc"].replace("Z", "+00:00"))
        if expiry - datetime.now(timezone.utc) < timedelta(minutes=45):
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
            pulls='; '.join('sudo docker --config /run/cc-contract-registry pull '+shlex.quote(ref)+' >> ~/cc-contract-evidence/image-pull.log 2>&1' for ref in images)
            remote = "set -e; mkdir -p ~/cc-contract-evidence; sudo install -d -m 700 /run/cc-contract-registry; trap 'sudo rm -rf /run/cc-contract-registry' EXIT; sudo docker --config /run/cc-contract-registry login ghcr.io -u ihsenalaya --password-stdin > ~/cc-contract-evidence/registry-login.log 2>&1; "+pulls
            command(ssh_args(directory, outputs) + [remote], input=match.group(1) + "\n", timeout=600)
            arguments=[image]
            if bundle:
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
                result = subprocess.run(ssh_args(directory, outputs) + ["bash -s -- " + ' '.join(shlex.quote(value) for value in arguments)], input=(ROOT / "scripts/qualify-host.sh").read_text(), text=True, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
            (directory / "qualification-exit.json").write_text(json.dumps({"returncode": result.returncode, "timestamp_utc": datetime.now(timezone.utc).isoformat()}) + "\n")
            return result.returncode
        finally:
            try:
                # Hash partial pull/download failures as well as completed workloads.
                finalize="set -e; mkdir -p ~/cc-contract-evidence; cd ~/cc-contract-evidence; sudo -n chown -R $(id -u):$(id -g) .; find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS"
                command(ssh_args(directory,outputs)+[finalize],timeout=60)
            finally:
                collect_and_release(directory)
    elif args.action == "collect-release":
        collect_and_release(directory)
    elif args.action == "release":
        release(directory)
    elif args.action == "destroy":
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
