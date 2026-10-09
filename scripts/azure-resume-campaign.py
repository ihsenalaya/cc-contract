"""Resume one retained VM using an approved, update-only Terraform plan.

Planning never starts compute. A separate user receipt binds the binary plan,
workload and bounded budget. All execution paths retain resources and stop the VM.
"""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location("retained_window", HERE.with_name("azure-window.py"))
window = importlib.util.module_from_spec(spec)
spec.loader.exec_module(window)
MAX_MINUTES = 90
MAX_BUDGET_USD = 15
MIN_START_MINUTES = 75
START_TIMEOUT_SECONDS = 15 * 60
ADDRESSES = frozenset({
    "azurerm_resource_group.window", "azurerm_virtual_network.window",
    "azurerm_subnet.window", "azurerm_network_security_group.window",
    "azurerm_subnet_network_security_group_association.window", "azurerm_public_ip.window",
    "azurerm_network_interface.window", "azurerm_logic_app_workflow.expiry",
    "azurerm_role_definition.expiry", "azurerm_role_assignment.expiry",
    "azurerm_logic_app_trigger_recurrence.expiry", "azurerm_logic_app_action_custom.expiry",
    "azurerm_linux_virtual_machine.gpu",
})
TAGGED = frozenset({"azurerm_resource_group.window", "azurerm_virtual_network.window",
    "azurerm_network_security_group.window", "azurerm_public_ip.window",
    "azurerm_network_interface.window", "azurerm_logic_app_workflow.expiry",
    "azurerm_linux_virtual_machine.gpu"})


def utcnow():
    return datetime.now(timezone.utc)


def load(path):
    return json.loads(path.read_text())


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def expiry_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise ValueError("Absolute UTC expiry required")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def single_ip(value):
    network = ipaddress.ip_network(value, strict=True)
    if network.version != 4 or network.prefixlen != 32:
        raise ValueError("SSH requires one IPv4 /32")
    return str(network)


def state_resources(state):
    result = {}
    for row in state.get("resources", []):
        address = row["type"] + "." + row["name"]
        if row.get("module") or row.get("mode", "managed") != "managed" or address in result:
            raise ValueError("Unexpected retained resource")
        instances = row.get("instances", [])
        if len(instances) != 1 or instances[0].get("index_key") is not None:
            raise ValueError("Unexpected retained resource instances")
        result[address] = instances[0]["attributes"]
    if set(result) != ADDRESSES:
        raise ValueError("Retained state must contain exactly the 13 original resources")
    return result


def unknown(value):
    if isinstance(value, dict):
        return any(unknown(item) for item in value.values())
    if isinstance(value, list):
        return any(unknown(item) for item in value)
    return value is True


def validate_plan(plan, original, inputs, old_inputs):
    """Inspect the actual binary plan; only tags, one SSH IP and expiry may change."""
    if any(plan.get("variables", {}).get(key, {}).get("value") != value for key, value in inputs.items()):
        raise ValueError("Saved plan variables differ from campaign inputs")
    changes = plan.get("resource_changes", [])
    if len(changes) != 13 or {row.get("address") for row in changes} != ADDRESSES:
        raise ValueError("Plan must retain exactly the 13 original addresses")
    if plan.get("resource_drift"):
        raise ValueError("Retained state drift requires review before resuming")
    tags = {"project": "cc-contract", "window": inputs["window_id"],
            "expires_at": inputs["expires_at_utc"], "workload_sha256": inputs["workload_sha256"],
            "host_script_sha256": inputs["host_script_sha256"]}
    for row in changes:
        address, change = row["address"], row["change"]
        if row.get("previous_address") or row.get("deposed") or change.get("actions") not in (["update"], ["no-op"]):
            raise ValueError("Creation, deletion, replacement or resource moves forbidden")
        if unknown(change.get("after_unknown", {})):
            raise ValueError("Unknown planned resource values forbidden")
        before, after = copy.deepcopy(change["before"]), copy.deepcopy(change["after"])
        if not before or not after or before != original[address]:
            raise ValueError("Retained resource identity differs")
        if before.get("id") != after.get("id"):
            raise ValueError("Resource identity may not change")
        if address in TAGGED:
            if after.get("tags") != tags:
                raise ValueError("New workload and expiry tags missing")
            before.pop("tags", None)
            after.pop("tags", None)
        if address == "azurerm_linux_virtual_machine.gpu":
            if before.get("virtual_machine_id") != original[address]["virtual_machine_id"]:
                raise ValueError("Actual VM UUID differs from retained state")
        if address == "azurerm_network_security_group.window":
            if inputs["ssh_source_cidr"] != old_inputs["ssh_source_cidr"]:
                single_ip(inputs["ssh_source_cidr"])
                rules = after.get("security_rule", [])
                old_rules = before.get("security_rule", [])
                if len(rules) != 1 or len(old_rules) != 1 or old_rules[0].get("source_address_prefix") != old_inputs["ssh_source_cidr"]:
                    raise ValueError("Unexpected SSH rule")
                if rules[0].get("source_address_prefix") != inputs["ssh_source_cidr"]:
                    raise ValueError("SSH rule differs from approved single IP")
                rules[0]["source_address_prefix"] = old_rules[0]["source_address_prefix"]
        if address == "azurerm_logic_app_action_custom.expiry":
            old_body, new_body = json.loads(before["body"]), json.loads(after["body"])
            expected = copy.deepcopy(old_body)
            if expected["expression"]["greaterOrEquals"] != ["@ticks(utcNow())", "@ticks('" + old_inputs["expires_at_utc"] + "')"]:
                raise ValueError("Original expiry guard differs")
            expected["expression"]["greaterOrEquals"][1] = "@ticks('" + inputs["expires_at_utc"] + "')"
            if new_body != expected:
                raise ValueError("Only the expiry timestamp may change in the independent guard")
            before.pop("body")
            after.pop("body")
        if before != after:
            raise ValueError("Unapproved resource field change: " + address)
    return changes


def saved_plan(directory):
    return json.loads(subprocess.check_output(["terraform", f"-chdir={window.MODULE}",
                      "show", "-json", str(directory / "plan.tfplan")], text=True))


def require_deallocated(vm_id, uuid):
    vm = window.az_json("vm", "show", "--ids", vm_id)
    if str(vm.get("vmId", "")).lower() != uuid.lower():
        raise ValueError("Actual retained VM UUID changed")
    view = window.az_json("vm", "get-instance-view", "--ids", vm_id)
    if "PowerState/deallocated" not in [row["code"] for row in view["instanceView"]["statuses"]]:
        raise ValueError("Retained VM must be deallocated")
    return vm


def verify_outputs(inputs, outputs, original):
    name = "cc-contract-" + inputs["window_id"]
    expected = f'/subscriptions/{inputs["subscription_id"]}/resourceGroups/{name}/providers/Microsoft.Compute/virtualMachines/{name}'
    if outputs["resource_group"]["value"] != name or outputs["vm_id"]["value"].lower() != expected.lower():
        raise ValueError("Retained resource group/VM output differs")
    if outputs["vm_id"]["value"].lower() != original["azurerm_linux_virtual_machine.gpu"]["id"].lower():
        raise ValueError("Retained output/state VM IDs differ")


def validate_approval(approval, summary, now):
    expected = {"schema_version": 1, "campaign_id": summary["campaign_id"],
                "retained_window": summary["retained_window"], "approved": True,
                "approval_source": "USER_EXPLICIT_APPROVAL", "plan_sha256": summary["plan_sha256"],
                "budget_forecast_usd": summary["budget_forecast_usd"],
                "max_window_minutes": summary["max_window_minutes"]}
    if any(approval.get(key) != value for key, value in expected.items()) or approval.get("approved") is not True:
        raise ValueError("Explicit user approval must match the plan, campaign and budget")
    planned = datetime.fromisoformat(summary["planned_at_utc"].replace("Z", "+00:00"))
    # A persistent explicit execution instruction can precede local planning.
    # Record when it was bound, without inventing a later human decision or
    # claiming the user inspected this binary plan's SHA.
    if approval.get('approved_at_utc') is None:
        if (approval.get('binding_source')!='EXISTING_EXPLICIT_USER_INSTRUCTION' or
                approval.get('user_has_not_seen_plan_sha256') is not True):
            raise ValueError('Earlier explicit instruction must be identified truthfully')
        approved=datetime.fromisoformat(approval['plan_bound_at_utc'].replace('Z','+00:00'))
    else:
        approved=datetime.fromisoformat(approval['approved_at_utc'].replace('Z','+00:00'))
    if approved.tzinfo is None or approved < planned or approved > now or not str(approval.get("message", "")).strip():
        raise ValueError("User approval timestamp or literal message missing")
    if not 0 < summary["budget_forecast_usd"] <= MAX_BUDGET_USD or not 0 < summary["max_window_minutes"] <= MAX_MINUTES:
        raise ValueError("Previously authorized budget/window exceeded")


def check_expiry(inputs, now, minimum=MIN_START_MINUTES):
    remaining = (expiry_time(inputs["expires_at_utc"]) - now).total_seconds()
    if remaining < minimum * 60 or remaining > MAX_MINUTES * 60:
        raise ValueError("Renewed expiry must leave the approved bounded execution window")


def verify_guard_and_tags(directory, plan, uuid):
    inputs, outputs = load(directory / "inputs.json"), load(directory / "outputs.json")
    vm = require_deallocated(outputs["vm_id"]["value"], uuid)
    expected_tags = {"project": "cc-contract", "window": inputs["window_id"],
                     "expires_at": inputs["expires_at_utc"], "workload_sha256": inputs["workload_sha256"],
                     "host_script_sha256": inputs["host_script_sha256"]}
    if vm.get("tags") != expected_tags:
        raise ValueError("Actual VM tags do not bind the renewed expiry and workload")
    rows = {row["address"]: row["change"]["after"] for row in plan["resource_changes"]}
    workflow = rows["azurerm_logic_app_workflow.expiry"]["id"]
    actual = window.az_json("rest", "--method", "get", "--url",
                           "https://management.azure.com" + workflow + "?api-version=2019-05-01")
    properties = actual.get("properties", {})
    if properties.get("state") != "Enabled":
        raise ValueError("Independent expiry workflow is not enabled")
    definition = properties.get("definition", {})
    expected = json.loads(rows["azurerm_logic_app_action_custom.expiry"]["body"])
    if definition.get("actions", {}).get("ExpiryGuard") != expected:
        raise ValueError("Actual Azure expiry guard differs from the approved renewed guard")
    trigger = definition.get("triggers", {}).get("ExpiryTick", {})
    if trigger.get("type") != "Recurrence" or trigger.get("recurrence", {}).get("frequency") != "Minute" or trigger["recurrence"].get("interval") != 1:
        raise ValueError("Independent minute expiry trigger missing")
    write_new(directory / "renewed-guard-readback.json", {"timestamp_utc": utcnow().isoformat(),
              "vm_uuid": uuid, "vm_tags": vm["tags"], "workflow": actual,
              "power_state": "PowerState/deallocated"})


def plan_campaign(args):
    if not 0 < args.max_window_minutes <= MAX_MINUTES or not 0 < args.budget_forecast_usd <= MAX_BUDGET_USD:
        raise ValueError("Previously authorized budget/window exceeded")
    old, directory = window.STATE / args.retained_window, window.STATE / args.campaign
    if old == directory or directory.exists():
        raise ValueError("A fresh campaign directory is required")
    old_inputs, outputs = load(old / "inputs.json"), load(old / "outputs.json")
    if old_inputs["window_id"] != args.retained_window:
        raise ValueError("Retained window identity differs")
    original = state_resources(load(old / "terraform.tfstate"))
    gpu = original["azurerm_linux_virtual_machine.gpu"]
    verify_outputs(old_inputs, outputs, original)
    require_deallocated(gpu["id"], gpu["virtual_machine_id"])
    bundle = window.verify_bundle(args.workload_bundle)
    if bundle.get("transport") != "FIXED_WORK_IR_CAMPAIGN":
        raise ValueError("Only the reviewed fixed-work campaign may resume this VM")
    directory.mkdir(mode=0o700)
    (directory / "workload-bundle.json").write_bytes(args.workload_bundle.read_bytes())
    inputs = dict(old_inputs)
    inputs.update(expires_at_utc=(utcnow() + timedelta(minutes=args.max_window_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  workload_sha256=window.sha(directory / "workload-bundle.json"),
                  host_script_sha256=window.sha(window.ROOT / "scripts/qualify-host.sh"))
    if args.ssh_source_cidr:
        inputs["ssh_source_cidr"] = single_ip(args.ssh_source_cidr)
    write_new(directory / "inputs.json", inputs)
    write_new(directory / "outputs.json", outputs)
    (directory / "id_ed25519").symlink_to((old / "id_ed25519").resolve(strict=True))
    if (old / "known_hosts").exists():
        (directory / "known_hosts").write_bytes((old / "known_hosts").read_bytes())
    with (directory / "plan.log").open("x") as log:
        window.tf("init", "-input=false", "-reconfigure", f"-backend-config=path={old / 'terraform.tfstate'}", stdout=log, stderr=subprocess.STDOUT)
        window.tf("plan", "-input=false", f"-var-file={directory / 'inputs.json'}", f"-out={directory / 'plan.tfplan'}", stdout=log, stderr=subprocess.STDOUT)
    plan = saved_plan(directory)
    changes = validate_plan(plan, original, inputs, old_inputs)
    write_new(directory / "plan.json", plan)
    summary = {"schema_version": 1, "campaign_id": args.campaign, "retained_window": args.retained_window,
               "planned_at_utc": utcnow().isoformat(), "plan_sha256": window.sha(directory / "plan.tfplan"),
               "expires_at_utc": inputs["expires_at_utc"], "max_window_minutes": args.max_window_minutes,
               "budget_forecast_usd": args.budget_forecast_usd, "workload_bundle_sha256": inputs["workload_sha256"],
               "host_script_sha256": inputs["host_script_sha256"], "retained_state_path": str(old / "terraform.tfstate"),
               "retained_state_sha256": window.sha(old / "terraform.tfstate"), "retained_vm_id": gpu["id"],
               "retained_vm_uuid": gpu["virtual_machine_id"], "old_inputs": old_inputs,
               "terraform_module_sha256": window.sha(window.MODULE / "main.tf"),
               "resume_controller_sha256": window.sha(HERE),
               "window_controller_sha256": window.sha(HERE.with_name("azure-window.py")),
               "planned_resources": [{"address": row["address"], "actions": row["change"]["actions"]} for row in changes],
               "approval_required": True, "created_resources": 0, "deleted_resources": 0,
               "temporary_resources_retained_for_user_decision": True}
    write_new(directory / "approved-workload-plan.json", summary)
    write_new(directory / "summary.json", summary)
    print(json.dumps(summary, indent=2))


def verify_run(directory, supplied_hash):
    summary, inputs = load(directory / "summary.json"), load(directory / "inputs.json")
    if supplied_hash != window.sha(directory / "plan.tfplan") or supplied_hash != summary["plan_sha256"]:
        raise ValueError("Matching explicitly approved binary plan hash required")
    validate_approval(load(directory / "user-approval.json"), summary, utcnow())
    state_path = Path(summary["retained_state_path"])
    expected_state = window.STATE / summary["retained_window"] / "terraform.tfstate"
    if state_path.resolve() != expected_state.resolve() or window.sha(state_path) != summary["retained_state_sha256"]:
        raise ValueError("Original retained backend changed since planning")
    if summary["campaign_id"] != directory.name or inputs["window_id"] != summary["retained_window"]:
        raise ValueError("Campaign/retained window binding differs")
    if summary["resume_controller_sha256"] != window.sha(HERE) or summary["terraform_module_sha256"] != window.sha(window.MODULE / "main.tf"):
        raise ValueError("Reviewed controller or infrastructure source changed")
    if summary["window_controller_sha256"] != window.sha(HERE.with_name("azure-window.py")) or load(directory / "approved-workload-plan.json") != summary:
        raise ValueError("Reviewed qualification controller or workload scope changed")
    if summary["workload_bundle_sha256"] != window.sha(directory / "workload-bundle.json") or summary["host_script_sha256"] != window.sha(window.ROOT / "scripts/qualify-host.sh"):
        raise ValueError("Planned workload bundle or host script changed")
    if inputs["workload_sha256"] != summary["workload_bundle_sha256"] or inputs["host_script_sha256"] != summary["host_script_sha256"] or inputs["expires_at_utc"] != summary["expires_at_utc"]:
        raise ValueError("Planned workload/expiry inputs changed")
    if window.verify_bundle(directory / "workload-bundle.json").get("transport") != "FIXED_WORK_IR_CAMPAIGN":
        raise ValueError("Reviewed fixed-work campaign required")
    original = state_resources(load(state_path))
    plan = saved_plan(directory)
    validate_plan(plan, original, inputs, summary["old_inputs"])
    gpu = original["azurerm_linux_virtual_machine.gpu"]
    if summary["retained_vm_uuid"] != gpu["virtual_machine_id"] or summary["retained_vm_id"] != gpu["id"]:
        raise ValueError("Planned retained VM identity changed")
    verify_outputs(inputs, load(directory / "outputs.json"), original)
    key = directory / "id_ed25519"
    expected_key = window.STATE / summary["retained_window"] / "id_ed25519"
    if not key.is_symlink() or key.resolve(strict=True) != expected_key.resolve(strict=True):
        raise ValueError("Campaign must reference the original private SSH key")
    check_expiry(inputs, utcnow())
    return summary, inputs, plan


def bounded_az_json(args, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Retained VM startup exceeded 15 minutes")
    raw = subprocess.check_output(["az", *args, "-o", "json", "--only-show-errors"],
                                  timeout=min(180, remaining))
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = raw.decode("cp1252")
    return json.loads(decoded)


def start_and_wait(vm_id, uuid, directory=None):
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    if directory is not None:
        write_new(directory / 'start-request.json',{'timestamp_utc':utcnow().isoformat(),
                  'monotonic_ns':time.monotonic_ns(),'scope':'AZURE_START_REQUEST_BEFORE_CONFIRMED_RUNNING',
                  'billing_start_established':False})
    window.command(["az", "vm", "start", "--ids", vm_id, "--no-wait", "--only-show-errors"], timeout=180)
    while time.monotonic() < deadline:
        view = bounded_az_json(["vm", "get-instance-view", "--ids", vm_id], deadline)
        codes = [row["code"] for row in view["instanceView"]["statuses"]]
        if directory is not None:
            with (directory / 'power-states.jsonl').open('a') as output:
                output.write(json.dumps({'timestamp_utc':utcnow().isoformat(),
                    'monotonic_ns':time.monotonic_ns(),'status_codes':codes,
                    'billing_start_established':False})+'\n')
                output.flush();os.fsync(output.fileno())
        if "PowerState/running" in codes:
            actual = bounded_az_json(["vm", "show", "--ids", vm_id], deadline)
            if str(actual.get("vmId", "")).lower() != uuid.lower():
                raise ValueError("Actual VM UUID changed during startup")
            return
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(10, remaining))
    raise TimeoutError("Retained VM startup exceeded 15 minutes")


def run_campaign(directory, supplied_hash):
    summary, inputs, plan = verify_run(directory, supplied_hash)
    if any((directory / name).exists() for name in ("run-start.json", "qualification-exit.json", "collection.json")):
        raise ValueError("Campaign already executed; preserve its separate original receipts")
    uuid, vm_id = summary["retained_vm_uuid"], summary["retained_vm_id"]
    vm = require_deallocated(vm_id, uuid)
    if vm.get("tags", {}).get("project") != "cc-contract" or vm.get("tags", {}).get("window") != inputs["window_id"]:
        raise ValueError("Retained VM project/window tags changed")
    started, failure, mutated, qualification_started = time.monotonic(), None, False, False
    started_utc = utcnow().isoformat()
    write_new(directory / "run-start.json", {"timestamp_utc": started_utc,
              "monotonic_ns": time.monotonic_ns(), "plan_sha256": supplied_hash,
              "scope": "RESUME_RETAINED_VM_FIXED_WORK_CAMPAIGN_EXPORT_AND_DEALLOCATION",
              "retained_vm_uuid": uuid})
    try:
        window.record_phase(directory, "renew_expiry_while_deallocated", "STARTED")
        with (directory / "apply.log").open("x") as log:
            window.tf("init", "-input=false", "-reconfigure", f"-backend-config=path={summary['retained_state_path']}", stdout=log, stderr=subprocess.STDOUT)
            mutated = True
            window.tf("apply", "-input=false", str(directory / "plan.tfplan"), stdout=log, stderr=subprocess.STDOUT)
        current_state = Path(summary["retained_state_path"]).read_bytes()
        # Evidence copy only: the actual Terraform backend remains the retained window.
        (directory / "terraform.tfstate").write_bytes(current_state)
        window.preserve_applied_identity(directory)
        outputs = load(directory / "outputs.json")
        outputs["expiry"]["value"] = inputs["expires_at_utc"]
        (directory / "outputs.json").write_text(json.dumps(outputs, indent=2) + "\n")
        verify_guard_and_tags(directory, plan, uuid)
        check_expiry(inputs, utcnow())
        window.record_phase(directory, "renew_expiry_while_deallocated", "FINISHED")
        window.record_phase(directory, "start_retained_vm", "STARTED")
        start_and_wait(vm_id, uuid, directory)
        window.record_phase(directory, "start_retained_vm", "FINISHED")
        qualification_started = True
        window.run_phase(directory, "qualify_collect_release", [sys.executable,
                         str(HERE.with_name("azure-window.py")), "qualify", "--window", directory.name])
    except BaseException as error:
        failure = type(error).__name__
        raise
    finally:
        release_error = None
        try:
            if mutated:
                # Even failure before SSH or host qualification must stop compute.
                if qualification_started and (directory / "release.json").exists():
                    try:
                        require_deallocated(vm_id, uuid)
                    except BaseException:
                        window.release(directory)
                else:
                    window.release(directory)
        except BaseException as error:
            release_error = type(error).__name__
            raise
        finally:
            finished_utc = utcnow().isoformat()
            write_new(directory / "run-exit.json", {"timestamp_utc": finished_utc,
                      "started_at_utc": started_utc, "finished_at_utc": finished_utc,
                      "monotonic_ns": time.monotonic_ns(), "elapsed_seconds": time.monotonic() - started,
                      "error_type": failure, "release_error_type": release_error,
                      "scope": "RESUME_RETAINED_VM_FIXED_WORK_CAMPAIGN_EXPORT_AND_DEALLOCATION",
                      "temporary_resources_retained_for_user_decision": True,
                      "resources_destroyed_automatically": False,
                      "deallocation_verified": release_error is None,
                      "analysis_and_user_decision_time_included": False})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "run"))
    parser.add_argument("--campaign", default="fixed-work-1010a")
    parser.add_argument("--retained-window", default="work-sample-1009b")
    parser.add_argument("--workload-bundle", type=Path)
    parser.add_argument("--ssh-source-cidr")
    parser.add_argument("--max-window-minutes", type=int, default=MAX_MINUTES)
    parser.add_argument("--budget-forecast-usd", type=float, default=MAX_BUDGET_USD)
    parser.add_argument("--approved-plan-sha256")
    args = parser.parse_args(argv)
    for value in (args.campaign, args.retained_window):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,20}", value):
            parser.error("Use a lowercase campaign/window identifier")
    native, config = window.STATE / "azure-native-cli-venv/bin/az", window.STATE / "azure-native-cli-config"
    if native.is_file() and (config / "azureProfile.json").is_file():
        os.environ["PATH"] = str(native.parent) + os.pathsep + os.environ["PATH"]
        os.environ["AZURE_CONFIG_DIR"] = str(config)
    if args.action == "plan":
        if args.workload_bundle is None:
            parser.error("--workload-bundle required for planning")
        plan_campaign(args)
    else:
        if not args.approved_plan_sha256:
            parser.error("--approved-plan-sha256 and user-approval.json required")
        run_campaign(window.STATE / args.campaign, args.approved_plan_sha256)
    return 0


if __name__ == "__main__":
    sys.exit(main())
