"""Bounded retained-VM pilot, disabled without a fresh plan-bound user receipt.

Does not create/destroy resources. Review prepares a plan and only reads Azure.
Run renews the existing independent expiry, then retains/deallocates on all exits.
The expiry update is preserved for a later read-only Terraform state refresh.
"""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = Path.home() / ".local/state/cc-contract"
RG = "cc-contract-work-sample-1009b"
VM = "/subscriptions/60f9b06a-66b1-437f-ac92-3b5e9720e34a/resourceGroups/" + RG + "/providers/Microsoft.Compute/virtualMachines/" + RG
UUID = "2986ddd2-c122-4884-8f42-d7ad3d0a38ef"
DISK_UUID = "323889df-fc1f-45ea-a54d-dd47ee8a1f52"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as f:
        f.write(json.dumps(value, indent=2) + "\n")


def az(*args):
    env = dict(os.environ, AZURE_CONFIG_DIR=str(STATE / "azure-native-cli-config"))
    p = subprocess.run([str(STATE / "azure-native-cli-venv/bin/az"), *args,
                        "--only-show-errors", "-o", "json"], capture_output=True, env=env, timeout=120)
    if p.returncode:
        raise RuntimeError("Azure operation failed: " + " ".join(args[:2]))
    return json.loads(p.stdout) if p.stdout.strip() else None


def inventory():
    vm = az("vm", "get-instance-view", "--ids", VM)
    disk = az("disk", "show", "--ids", vm["storageProfile"]["osDisk"]["managedDisk"]["id"])
    if (vm["vmId"] != UUID or disk["uniqueId"] != DISK_UUID or
            vm["hardwareProfile"]["vmSize"] != "Standard_NCC40ads_H100_v5" or
            "PowerState/deallocated" not in [x["code"] for x in vm["instanceView"]["statuses"]]):
        raise ValueError("Retained VM identity or power state differs")
    resources = az("resource", "list", "-g", RG)
    workflows = [r for r in resources if r["type"].lower() == "microsoft.logic/workflows"]
    if len(resources) != 7 or len(workflows) != 1:
        raise ValueError("Retained resource inventory differs")
    guard = az("resource", "show", "--ids", workflows[0]["id"], "--api-version", "2019-05-01")
    validate_guard(guard)
    scope = VM.split("/providers/")[0]
    assignments = az("role", "assignment", "list", "--scope", scope)
    assigned = [x for x in assignments if x["principalId"] == guard["identity"]["principalId"]]
    permissions_ok = False
    required = {"Microsoft.Compute/virtualMachines/read", "Microsoft.Compute/virtualMachines/instanceView/read",
                "Microsoft.Compute/virtualMachines/deallocate/action"}
    for assignment in assigned:
        roles = az("role", "definition", "list", "--name", assignment["roleDefinitionId"].split("/")[-1])
        for role in roles:
            for permission in role["permissions"]:
                if set(permission["actions"]) == required and not permission["notActions"]:
                    permissions_ok = True
    if not permissions_ok:
        raise ValueError("Existing expiry deallocation permission unverified")
    return dict(vm=vm, disk=disk, resources=resources, guard=guard,
                guard_permissions_verified=True, checked_utc=datetime.now(timezone.utc).isoformat(), mutations=0)


def validate_guard(guard):
    properties = guard["properties"]
    definition = properties["definition"]
    tick = definition["triggers"]["ExpiryTick"]
    expiry = definition["actions"]["ExpiryGuard"]
    operations = expiry["actions"]
    uri = "https://management.azure.com" + VM
    if (properties["state"] != "Enabled" or tick["type"] != "Recurrence" or
            tick["recurrence"] != {"frequency": "Minute", "interval": 1} or
            operations["GetState"]["inputs"]["method"] != "GET" or
            operations["GetState"]["inputs"]["uri"] != uri + "/instanceView?api-version=2024-03-01" or
            operations["IfAllocated"]["actions"]["Deallocate"]["inputs"]["method"] != "POST" or
            operations["IfAllocated"]["actions"]["Deallocate"]["inputs"]["uri"] != uri + "/deallocate?api-version=2024-03-01"):
        raise ValueError("Independent minute deallocation guard differs")
    if expiry["expression"]["greaterOrEquals"][0] != "@ticks(utcNow())":
        raise ValueError("Expiry expression differs")
    conditional = operations["IfAllocated"]
    auth = {"type": "ManagedServiceIdentity", "audience": "https://management.azure.com/"}
    if (set(definition["actions"]) != {"ExpiryGuard"} or set(definition["triggers"]) != {"ExpiryTick"} or
            expiry["type"] != "If" or set(operations) != {"GetState", "IfAllocated"} or
            conditional["type"] != "If" or conditional["runAfter"] != {"GetState": ["Succeeded"]} or
            conditional["expression"] != {"not": {"contains": ["@string(body('GetState'))", "PowerState/deallocated"]}} or
            set(conditional["actions"]) != {"Deallocate"} or
            operations["GetState"]["inputs"]["authentication"] != auth or
            conditional["actions"]["Deallocate"]["inputs"]["authentication"] != auth):
        raise ValueError("Deallocation guard control flow or managed identity differs")


def validate_approval(plan, receipt, plan_hash, now):
    if (plan.get("protocol") != "state-continuity-pilot-v0.1" or plan.get("vm_id") != VM or
            plan.get("vm_uuid") != UUID or plan.get("disk_uuid") != DISK_UUID or
            plan.get("runs") != 50 or plan.get("gpu_parallelism") != 1 or
            plan.get("creates") != 0 or plan.get("destroys") != 0 or
            plan.get("max_minutes") != 30 or plan.get("budget_usd") != 5 or
            not re.fullmatch(r"ghcr.io/ihsenalaya/cc-contract-continuity@sha256:[a-f0-9]{64}", plan.get("image", "")) or
            receipt.get("approved_by") != "user" or receipt.get("approved") is not True or
            receipt.get("plan_sha256") != plan_hash or receipt.get("protocol") != plan["protocol"] or
            receipt.get("max_minutes") != 30 or receipt.get("budget_usd") != 5 or
            receipt.get("reuse_completed_authorization") is not False):
        raise ValueError("Fresh user approval must match this exact 30-minute/5-USD plan")
    approved = datetime.fromisoformat(receipt["approved_utc"])
    if approved.tzinfo is None or not 0 <= (now - approved).total_seconds() <= 3600:
        raise ValueError("Approval must be fresh; never reuse a completed window")


def review(args):
    if not re.fullmatch(r"ghcr.io/ihsenalaya/cc-contract-continuity@sha256:[a-f0-9]{64}", args.image or ""):
        raise ValueError("Qualified immutable image required")
    args.directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    live = inventory()
    write(args.directory / "inventory.json", live)
    source = ROOT / "scripts/run-continuity-host.sh"
    plan = dict(protocol="state-continuity-pilot-v0.1", image=args.image, vm_id=VM,
                vm_uuid=UUID, disk_uuid=DISK_UUID, creates=0, destroys=0,
                max_minutes=30, budget_usd=5, runs=50, gpu_parallelism=1,
                source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                host_script_sha256=sha(source), controller_sha256=sha(Path(__file__)),
                schedule_sha256=sha(ROOT / "experiments/state-continuity-schedule-v0.1.json"),
                guard_id=live["guard"]["id"], guard_definition_sha256=hashlib.sha256(
                    json.dumps(live["guard"]["properties"]["definition"], sort_keys=True).encode()).hexdigest(),
                approval_granted=False)
    write(args.directory / "plan.json", plan)
    print(json.dumps({"plan_sha256": sha(args.directory / "plan.json"), "vm_state": "DEALLOCATED", "STOP": "WAIT_FOR_NEW_USER_APPROVAL"}))


def verify_archive(raw):
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("Evidence byte limit exceeded")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive:
            if member.isdir():
                continue
            name = member.name.removeprefix("./")
            if (not member.isfile() or member.size > 8 * 1024 * 1024 or
                    name in files or name.startswith("/") or ".." in Path(name).parts or len(files) >= 100):
                raise ValueError("Unsafe evidence archive")
            files[name] = archive.extractfile(member).read()
    hashes = json.loads(files["hashes.json"])
    if set(hashes) != set(files) - {"hashes.json"}:
        raise ValueError("Evidence manifest membership differs")
    for name, value in hashes.items():
        if hashlib.sha256(files[name]).hexdigest() != value:
            raise ValueError("Evidence hash mismatch")
    return dict(archive_sha256=hashlib.sha256(raw).hexdigest(), files=len(files), hashes_verified=True)


def execute(args):
    plan_path = args.directory / "plan.json"
    plan = json.loads(plan_path.read_text())
    validate_approval(plan, json.loads(args.approval.read_text()), sha(plan_path), datetime.now(timezone.utc))
    if plan["controller_sha256"] != sha(Path(__file__)) or plan["host_script_sha256"] != sha(ROOT / "scripts/run-continuity-host.sh"):
        raise ValueError("Qualified executable source changed")
    # An exclusive receipt prevents repeat execution with a previous approval.
    write(args.directory / "execution-attempt.json", dict(started_utc=datetime.now(timezone.utc).isoformat()))
    live = inventory()
    definition = live["guard"]["properties"]["definition"]
    if hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest() != plan["guard_definition_sha256"]:
        raise ValueError("Guard changed since review")
    original = STATE / "work-sample-1009b"
    outputs = json.loads((original / "outputs.json").read_text())
    ssh = ["ssh", "-F", "/dev/null", "-i", str(original / "id_ed25519"), "-o", "BatchMode=yes",
           "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=yes", "-o",
           "UserKnownHostsFile=" + str(STATE / "fixed-work-1010a/known_hosts"),
           "cccontract@" + outputs["ssh_address"]["value"]]
    # Resolve existing registry credentials locally before risking paid compute.
    auth = subprocess.run(["gh", "auth", "status", "--show-token"], capture_output=True, timeout=15)
    match = re.search(r"Token:\s*(\S+)", (auth.stdout + auth.stderr).decode())
    if auth.returncode or not match:
        raise ValueError("Registry authentication unavailable locally; VM remains off")
    registry_token = match.group(1)
    expires = datetime.now(timezone.utc) + timedelta(minutes=28)
    renewed = copy.deepcopy(definition)
    renewed["actions"]["ExpiryGuard"]["expression"]["greaterOrEquals"][1] = "@ticks('" + expires.strftime("%Y-%m-%dT%H:%M:%SZ") + "')"
    body = args.directory / "guard-update.json"
    write(body, {"properties": {"definition": renewed}})
    start_attempted = False
    try:
        az("rest", "--method", "patch", "--url", "https://management.azure.com" + plan["guard_id"] + "?api-version=2019-05-01", "--body", "@" + str(body))
        actual = az("resource", "show", "--ids", plan["guard_id"], "--api-version", "2019-05-01")
        validate_guard(actual)
        if actual["properties"]["definition"] != renewed:
            raise ValueError("Renewed guard readback differs")
        write(args.directory / "renewed-guard.json", actual)
        inventory()  # prove still deallocated immediately before start
        start_attempted = True
        write(args.directory / "start-request.json", {"utc": datetime.now(timezone.utc).isoformat()})
        az("vm", "start", "--ids", VM, "--no-wait")
        ready_until = time.monotonic() + 480
        while True:
            probe = subprocess.run(ssh + ["true"], capture_output=True, timeout=10)
            if probe.returncode == 0:
                break
            if time.monotonic() > ready_until:
                raise RuntimeError("SSH deadline: stop and repair locally")
            time.sleep(5)
        login = subprocess.run(ssh + ["sudo -n install -d -m 700 /run/cc-continuity-registry && "
                         "sudo -n docker --config /run/cc-continuity-registry login ghcr.io -u ihsenalaya --password-stdin"],
                         input=(registry_token + "\n").encode(), capture_output=True, timeout=30)
        registry_token = None
        if login.returncode:
            raise RuntimeError("Registry login failed; deallocate before diagnosis")
        remote = "/home/cccontract/cc-continuity-" + args.directory.name
        command = "bash -s -- " + shlex.quote(plan["image"]) + " " + shlex.quote(remote)
        with (args.directory / "host.stdout").open("xb") as out, (args.directory / "host.stderr").open("xb") as err:
            result = subprocess.run(ssh + [command], input=(ROOT / "scripts/run-continuity-host.sh").read_bytes(),
                                    stdout=out, stderr=err, timeout=810)
        # Small originals are collected before release; analysis comes afterwards.
        export = subprocess.run(ssh + ["tar -czf - -C " + shlex.quote(remote) + " ."], capture_output=True, timeout=90, check=True)
        (args.directory / "originals.tar.gz").write_bytes(export.stdout)
        write(args.directory / "collection.json", verify_archive(export.stdout))
        if result.returncode:
            raise RuntimeError("Host qualification or pilot failed; keep partial originals")
    finally:
        if start_attempted:
            az("vm", "deallocate", "--ids", VM, "--no-wait")
            deadline = time.monotonic() + 180
            while True:
                vm = az("vm", "get-instance-view", "--ids", VM)
                if "PowerState/deallocated" in [r["code"] for r in vm["instanceView"]["statuses"]]:
                    write(args.directory / "release.json", dict(utc=datetime.now(timezone.utc).isoformat(),
                          power_state="PowerState/deallocated", disk_retained=True, resources_destroyed=0))
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("Deallocation not confirmed; independent expiry remains armed")
                time.sleep(5)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("review", "run"))
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--image")
    p.add_argument("--approval", type=Path)
    args = p.parse_args()
    os.umask(0o077)
    if not re.fullmatch(r"[a-z0-9-]{3,48}", args.directory.name):
        p.error("Use a simple unique private window directory name")
    if args.action == "review":
        review(args)
    elif args.approval is None:
        p.error("Explicit fresh user approval receipt required; no action taken")
    else:
        execute(args)


if __name__ == "__main__":
    main()
