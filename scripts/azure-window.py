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
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["plan", "run", "apply", "qualify", "collect-release", "release", "destroy"])
    p.add_argument("--window", required=True)
    p.add_argument("--ssh-source-cidr")
    p.add_argument("--approved-plan-sha256")
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
        # Public key only enters Terraform. Private key stays off the Windows workspace.
        command(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(directory / "id_ed25519")])
        account = az_json("account", "show")
        inputs = {"subscription_id": account["id"], "window_id": args.window, "ssh_public_key": (directory / "id_ed25519.pub").read_text().strip(), "ssh_source_cidr": args.ssh_source_cidr, "expires_at_utc": (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
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
        (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
    elif args.action == "apply":
        if args.approved_plan_sha256 != sha(directory / "plan.tfplan"):
            p.error("explicit user-approved matching plan hash required")
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
        ensure_window(directory)
        print("Approved temporary window provisioned; independent expiry configured. Begin immediate qualification.")
    elif args.action == "qualify":
        _, outputs = ensure_window(directory)
        try:
            if (directory / "qualification-exit.json").exists() or (directory / "collection.json").exists():
                raise RuntimeError("Window already executed; preserve finalized evidence and use a new window")
            image = (ROOT / ".local/cuda/remote-digest").read_text().strip()
            assert re.fullmatch(r"ghcr.io/ihsenalaya/cc-contract-cuda@sha256:[a-f0-9]{64}", image)
            # Credential stays in a root-only RAM directory and is removed after pull.
            credential_file = Path.home() / ".config/gh/hosts.yml"
            match = re.search(r"^\s+oauth_token:\s*(\S+)\s*$", credential_file.read_text(), re.M)
            if not match:
                raise RuntimeError("GHCR read credential unavailable")
            remote = "set -e; mkdir -p ~/cc-contract-evidence; sudo install -d -m 700 /run/cc-contract-registry; trap 'sudo rm -rf /run/cc-contract-registry' EXIT; sudo docker --config /run/cc-contract-registry login ghcr.io -u ihsenalaya --password-stdin > ~/cc-contract-evidence/registry-login.log 2>&1; sudo docker --config /run/cc-contract-registry pull " + shlex.quote(image) + " > ~/cc-contract-evidence/image-pull.log 2>&1"
            command(ssh_args(directory, outputs) + [remote], input=match.group(1) + "\n", timeout=600)
            with (directory / "qualification-session.log").open("w") as log:
                result = subprocess.run(ssh_args(directory, outputs) + ["bash -s -- " + shlex.quote(image)], input=(ROOT / "scripts/qualify-host.sh").read_text(), text=True, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
            (directory / "qualification-exit.json").write_text(json.dumps({"returncode": result.returncode, "timestamp_utc": datetime.now(timezone.utc).isoformat()}) + "\n")
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
