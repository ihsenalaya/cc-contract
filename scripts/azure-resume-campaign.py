"""Resume one retained VM using an approved, update-only Terraform plan.

Planning never starts compute. A separate user receipt binds the binary plan,
workload and bounded budget. All execution paths retain resources and stop the VM.
"""
import argparse
import copy
import hashlib
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
SSH_ATTEMPT_SECONDS = 15
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
REFRESH_COMPUTED_MODE = "computed-values"
REFRESH_DISK_CASE_MODE = "os-disk-arm-id-case"
REFRESH_MODES = (REFRESH_COMPUTED_MODE, REFRESH_DISK_CASE_MODE)
REFRESH_ADDRESSES = frozenset({"azurerm_logic_app_workflow.expiry",
    "azurerm_network_interface.window", "azurerm_public_ip.window",
    "azurerm_role_definition.expiry", "azurerm_subnet.window", "azurerm_virtual_network.window"})


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


def copy_new(source, target):
    """Preserve the exact original bytes, rather than reserializing evidence."""
    with target.open("xb") as stream:
        stream.write(source.read_bytes())
        stream.flush()
        os.fsync(stream.fileno())
    target.chmod(0o600)


def plan_values(values):
    module = values.get("root_module", {})
    if module.get("child_modules"):
        raise ValueError("Refresh may not include modules")
    result = {}
    for row in module.get("resources", []):
        address = row.get("address")
        if (address in result or row.get("mode") != "managed" or row.get("index") is not None
                or row.get("provider_name") != "registry.terraform.io/hashicorp/azurerm"
                or address != row.get("type", "") + "." + row.get("name", "")):
            raise ValueError("Unexpected refreshed resource address or provider")
        result[address] = row["values"]
    if set(result) != ADDRESSES:
        raise ValueError("Refresh must contain exactly the 13 original resources")
    return result


def validate_nic_readback(actual, original):
    nic = original["azurerm_network_interface.window"]
    vm = original["azurerm_linux_virtual_machine.gpu"]
    if (str(actual.get("id", "")).lower() != nic["id"].lower()
            or str(actual.get("virtualMachine", {}).get("id", "")).lower() != vm["id"].lower()
            or actual.get("name") != nic["name"]
            or actual.get("resourceGroup") != nic["resource_group_name"]):
        raise ValueError("Actual NIC does not belong to the retained VM")
    mac = str(actual.get("macAddress", "")).upper().replace(":", "-")
    if not re.fullmatch(r"(?:[0-9A-F]{2}-){5}[0-9A-F]{2}", mac):
        raise ValueError("Actual retained NIC MAC address missing")
    return mac


def expected_computed_refresh(original, nic_readback):
    expected = copy.deepcopy(original)
    # Terraform normalizes this optional block during schema decoding without
    # listing it in resource_drift. Check it explicitly; never ignore VM fields.
    vm = expected["azurerm_linux_virtual_machine.gpu"]
    if vm.get("termination_notification") is not None:
        raise ValueError("Original VM optional-block normalization differs")
    vm["termination_notification"] = []
    workflow = expected["azurerm_logic_app_workflow.expiry"]
    if len(workflow["identity"]) != 1 or workflow["identity"][0].get("identity_ids") is not None:
        raise ValueError("Original workflow identity normalization differs")
    workflow["identity"][0]["identity_ids"] = []
    nic = expected["azurerm_network_interface.window"]
    if nic.get("dns_servers") is not None or nic.get("mac_address") != "" or nic.get("virtual_machine_id") != "":
        raise ValueError("Original NIC computed values differ")
    nic.update(dns_servers=[], mac_address=validate_nic_readback(nic_readback, original),
               virtual_machine_id=original["azurerm_linux_virtual_machine.gpu"]["id"])
    public_ip = expected["azurerm_public_ip.window"]
    if public_ip.get("ip_tags") is not None or public_ip.get("zones") is not None:
        raise ValueError("Original public IP empty-value normalization differs")
    public_ip.update(ip_tags={}, zones=[])
    permissions = expected["azurerm_role_definition.expiry"]["permissions"]
    if len(permissions) != 1:
        raise ValueError("Original deallocation permissions differ")
    for key in ("not_actions", "data_actions", "not_data_actions"):
        if permissions[0].get(key) is not None:
            raise ValueError("Original deallocation permission normalization differs")
        permissions[0][key] = []
    subnet = expected["azurerm_subnet.window"]
    nsg = original["azurerm_network_security_group.window"]["id"]
    association = original["azurerm_subnet_network_security_group_association.window"]
    if (subnet.get("network_security_group_id") != "" or subnet.get("service_endpoint_policy_ids") is not None
            or association.get("network_security_group_id") != nsg
            or association.get("subnet_id") != subnet["id"]
            or subnet.get("address_prefixes") != ["10.239.0.0/24"]):
        raise ValueError("Original subnet/NSG association differs")
    subnet.update(network_security_group_id=nsg, service_endpoint_policy_ids=[])
    vnet = expected["azurerm_virtual_network.window"]
    if vnet.get("subnet") != [] or subnet["id"] != vnet["id"] + "/subnets/" + subnet["name"]:
        raise ValueError("Original VNet/subnet identity differs")
    vnet["subnet"] = [{key: copy.deepcopy(subnet[key]) for key in (
        "id", "name", "address_prefixes", "default_outbound_access_enabled", "delegation",
        "private_endpoint_network_policies", "private_link_service_network_policies_enabled",
        "route_table_id", "service_endpoint", "service_endpoint_policy_ids")}]
    vnet["subnet"][0]["security_group"] = nsg
    return expected


def expected_disk_id_case(original, vm_readback, disk_readback):
    """Reconcile only the observed uppercase RG spelling of the same OS disk."""
    gpu = original["azurerm_linux_virtual_machine.gpu"]
    blocks = gpu.get("os_disk", [])
    if len(blocks) != 1 or not isinstance(blocks[0], dict):
        raise ValueError("Exactly one retained OS disk is required")
    before = blocks[0].get("id")
    name = blocks[0].get("name")
    vm_prefix = gpu["id"].split("/providers/Microsoft.Compute/virtualMachines/")
    if (len(vm_prefix) != 2 or not isinstance(before, str) or not isinstance(name, str)
            or before != gpu.get("os_managed_disk_id")
            or before != vm_prefix[0] + "/providers/Microsoft.Compute/disks/" + name):
        raise ValueError("Original OS disk identity or resource group differs")
    match = re.fullmatch(r"(/subscriptions/[^/]+/resourceGroups/)([^/]+)(/providers/Microsoft\.Compute/disks/[^/]+)", before)
    if not match:
        raise ValueError("Original OS disk ARM ID malformed")
    after = match[1] + match[2].upper() + match[3]
    if after == before:
        raise ValueError("No reviewed OS disk RG case change exists")
    vm_readback, disk_readback = vm_readback or {}, disk_readback or {}
    actual_disk = vm_readback.get("storageProfile", {}).get("osDisk", {}).get("managedDisk", {}).get("id")
    if (str(vm_readback.get("id", "")).lower() != gpu["id"].lower()
            or str(vm_readback.get("vmId", "")).lower() != gpu["virtual_machine_id"].lower()
            or actual_disk != after
            or str(disk_readback.get("id", "")).lower() != before.lower()
            or str(disk_readback.get("managedBy", "")).lower() != gpu["id"].lower()
            or disk_readback.get("name") != name
            or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", str(disk_readback.get("uniqueId", "")))):
        raise ValueError("Live original VM and OS disk case identity differ")
    expected = copy.deepcopy(original)
    expected["azurerm_linux_virtual_machine.gpu"]["os_disk"][0]["id"] = after
    expected["azurerm_linux_virtual_machine.gpu"]["os_managed_disk_id"] = after
    return expected


def validate_refresh_plan(plan, original_state, inputs, nic_readback=None, *,
                          normalization_mode=REFRESH_COMPUTED_MODE, vm_readback=None, disk_readback=None):
    """Accept a separately reviewed computed-value or exact OS disk RG case refresh.

    This does not authorize resource updates. The normal resume plan continues
    to reject every resource_drift entry after this separate state operation.
    """
    original = state_resources(original_state)
    if (plan.get("terraform_version") != "1.12.2" or plan.get("complete") is not True
            or plan.get("errored") is not False):
        raise ValueError("A complete Terraform 1.12.2 refresh plan is required")
    variables = {key: row.get("value") for key, row in plan.get("variables", {}).items()}
    expected_variables = dict(inputs)
    expected_variables.setdefault("confidential_image_id", original["azurerm_linux_virtual_machine.gpu"]["source_image_id"])
    expected_variables.setdefault("model_container_scope", "")
    if variables != expected_variables:
        raise ValueError("Refresh variables must equal the retained inputs")
    drift = plan.get("resource_drift", [])
    if normalization_mode == REFRESH_COMPUTED_MODE:
        if len(drift) != 6 or {row.get("address") for row in drift} != REFRESH_ADDRESSES:
            raise ValueError("Refresh permits exactly the six reviewed computed-value resources")
        expected = expected_computed_refresh(original, nic_readback)
    elif normalization_mode == REFRESH_DISK_CASE_MODE:
        if len(drift) != 1 or drift[0].get("address") != "azurerm_linux_virtual_machine.gpu":
            raise ValueError("Disk case refresh permits exactly one original VM drift")
        expected = expected_disk_id_case(original, vm_readback, disk_readback)
    else:
        raise ValueError("Unknown reviewed state normalization mode")
    for row in drift:
        address, change = row["address"], row["change"]
        if (row.get("previous_address") or row.get("deposed") or change.get("importing")
                or change.get("actions") != ["update"] or unknown(change.get("after_unknown", {}))
                or change.get("before") != original[address] or change.get("after") != expected[address]):
            raise ValueError("Unapproved computed-value drift: " + address)
    expected_outputs = copy.deepcopy(original_state["outputs"])
    for output in expected_outputs.values():
        if output.get("sensitive", False) is not False:
            raise ValueError("Unexpected sensitive retained output")
        output["sensitive"] = False
    prior = plan.get("prior_state", {}).get("values", {})
    planned = plan.get("planned_values", {})
    if (plan_values(prior) != expected or prior.get("outputs") != expected_outputs
            or planned.get("root_module") != {} or planned.get("outputs") != expected_outputs):
        # Terraform 1.12.2 refresh-only stores refreshed resources in prior_state
        # and has an empty planned root. Reject a normal resource mutation plan.
        raise ValueError("Refresh values or outputs differ from the reviewed state")
    changes = plan.get("resource_changes", [])
    if changes and (len(changes) != 13 or {row.get("address") for row in changes} != ADDRESSES):
        raise ValueError("Unexpected refresh resource actions")
    for row in changes:
        change = row["change"]
        if (row.get("previous_address") or row.get("deposed") or change.get("importing")
                or change.get("actions") != ["no-op"] or unknown(change.get("after_unknown", {}))
                or change.get("before") != expected[row["address"]] or change.get("after") != expected[row["address"]]):
            raise ValueError("Refresh-only plan may not mutate Azure resources")
    outputs = plan.get("output_changes", {})
    if set(outputs) != set(original_state["outputs"]):
        raise ValueError("Refresh outputs missing or added")
    for name, change in outputs.items():
        value = original_state["outputs"][name]["value"]
        if (change.get("actions") != ["no-op"] or change.get("before") != value
                or change.get("after") != value or unknown(change.get("after_unknown", False))):
            raise ValueError("Refresh may not change outputs")
    return expected


def refresh_readbacks(mode, original, actual_vm):
    if mode == REFRESH_COMPUTED_MODE:
        return {"nic-readback.json": window.az_json("network", "nic", "show", "--ids",
                original["azurerm_network_interface.window"]["id"])}
    if mode == REFRESH_DISK_CASE_MODE:
        gpu = original["azurerm_linux_virtual_machine.gpu"]
        blocks = gpu.get("os_disk", [])
        disk_id = gpu.get("os_managed_disk_id")
        if (len(blocks) != 1 or blocks[0].get("id") != disk_id or not isinstance(disk_id, str)
                or not re.fullmatch(r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.Compute/disks/[^/]+", disk_id)):
            raise ValueError("Original OS disk readback identity malformed")
        return {"vm-readback.json": actual_vm,
                "disk-readback.json": window.az_json("disk", "show", "--ids", disk_id)}
    raise ValueError("Unknown reviewed state normalization mode")


def validate_bound_refresh(plan, state, inputs, mode, readbacks):
    required = ({"nic-readback.json"} if mode == REFRESH_COMPUTED_MODE else
                {"vm-readback.json", "disk-readback.json"} if mode == REFRESH_DISK_CASE_MODE else set())
    if not required or set(readbacks) != required:
        raise ValueError("Reviewed refresh readback set differs")
    return validate_refresh_plan(plan, state, inputs, readbacks.get("nic-readback.json"),
        normalization_mode=mode, vm_readback=readbacks.get("vm-readback.json"),
        disk_readback=readbacks.get("disk-readback.json"))


def verify_refresh_readback_identity(mode, saved, current):
    if (mode == REFRESH_DISK_CASE_MODE
            and saved["disk-readback.json"]["uniqueId"] != current["disk-readback.json"].get("uniqueId")):
        raise ValueError("Live retained OS disk uniqueId changed since refresh planning")


def refresh_case_changes(mode, original, expected):
    if mode != REFRESH_DISK_CASE_MODE:
        return {}
    before, after = original["azurerm_linux_virtual_machine.gpu"], expected["azurerm_linux_virtual_machine.gpu"]
    return {"azurerm_linux_virtual_machine.gpu.os_disk[0].id": {"before": before["os_disk"][0]["id"], "after": after["os_disk"][0]["id"]},
            "azurerm_linux_virtual_machine.gpu.os_managed_disk_id": {"before": before["os_managed_disk_id"], "after": after["os_managed_disk_id"]}}


def refresh_plan(args):
    old, directory = window.STATE / args.retained_window, window.STATE / args.refresh_id
    if old == directory or directory.exists():
        raise ValueError("A fresh refresh evidence directory is required")
    mode = getattr(args, "state_normalization_mode", REFRESH_COMPUTED_MODE)
    if mode not in REFRESH_MODES:
        raise ValueError("Unknown reviewed state normalization mode")
    original_inputs, original_outputs, state = load(old / "inputs.json"), load(old / "outputs.json"), load(old / "terraform.tfstate")
    if original_inputs["window_id"] != args.retained_window:
        raise ValueError("Retained window identity differs")
    original = state_resources(state)
    verify_outputs(original_inputs, original_outputs, original)
    inputs, outputs = operational_inputs(original_inputs, state)
    gpu = original["azurerm_linux_virtual_machine.gpu"]
    actual_vm = require_deallocated(gpu["id"], gpu["virtual_machine_id"])
    readbacks = refresh_readbacks(mode, original, actual_vm)
    if mode == REFRESH_COMPUTED_MODE:
        validate_nic_readback(readbacks["nic-readback.json"], original)
    else:
        expected_disk_id_case(original, readbacks["vm-readback.json"], readbacks["disk-readback.json"])
    directory.mkdir(mode=0o700)
    for source, target in (("terraform.tfstate", "terraform.tfstate-before"), ("inputs.json", "inputs.json"), ("outputs.json", "outputs.json")):
        copy_new(old / source, directory / target)
    write_new(directory / "operational-inputs.json", inputs)
    write_new(directory / "operational-outputs.json", outputs)
    for name, data in readbacks.items():
        write_new(directory / name, data)
    with (directory / "plan.log").open("x") as log:
        window.tf("init", "-input=false", "-reconfigure", f"-backend-config=path={old / 'terraform.tfstate'}", stdout=log, stderr=subprocess.STDOUT)
        window.tf("plan", "-refresh-only", "-input=false", f"-var-file={directory / 'operational-inputs.json'}", f"-out={directory / 'plan.tfplan'}", stdout=log, stderr=subprocess.STDOUT)
    plan = saved_plan(directory)
    write_new(directory / "plan.json", plan)
    expected = validate_bound_refresh(plan, state, inputs, mode, readbacks)
    if window.sha(old / "terraform.tfstate") != window.sha(directory / "terraform.tfstate-before"):
        raise ValueError("Retained backend changed during read-only refresh planning")
    if any(window.sha(old / name) != window.sha(directory / name) for name in ("inputs.json", "outputs.json")):
        raise ValueError("Original retained receipts changed during refresh planning")
    actual_vm = require_deallocated(gpu["id"], gpu["virtual_machine_id"])
    current_readbacks = refresh_readbacks(mode, original, actual_vm)
    verify_refresh_readback_identity(mode, readbacks, current_readbacks)
    validate_bound_refresh(plan, state, inputs, mode, current_readbacks)
    summary = {"schema_version": 1, "state": "REVIEWED_REFRESH_ONLY_STATE_PLAN",
        "scope": "LOCAL_TERRAFORM_STATE_RECONCILIATION_ONLY", "refresh_id": args.refresh_id,
        "state_normalization_mode": mode,
        "retained_window": args.retained_window, "planned_at_utc": utcnow().isoformat(),
        "plan_sha256": window.sha(directory / "plan.tfplan"), "plan_json_sha256": window.sha(directory / "plan.json"),
        "retained_state_path": str(old / "terraform.tfstate"), "retained_state_sha256": window.sha(directory / "terraform.tfstate-before"),
        "inputs_sha256": window.sha(directory / "inputs.json"), "outputs_sha256": window.sha(directory / "outputs.json"),
        "operational_inputs_sha256": window.sha(directory / "operational-inputs.json"),
        "operational_outputs_sha256": window.sha(directory / "operational-outputs.json"),
        "operational_expiry_utc": inputs["expires_at_utc"],
        "readback_sha256": {name: window.sha(directory / name) for name in readbacks},
        "retained_vm_id": gpu["id"], "retained_vm_uuid": gpu["virtual_machine_id"],
        "terraform_module_sha256": window.sha(window.MODULE / "main.tf"), "resume_controller_sha256": window.sha(HERE),
        "window_controller_sha256": window.sha(HERE.with_name("azure-window.py")),
        "resource_drift_addresses": sorted(row["address"] for row in plan["resource_drift"]), "azure_resource_mutations": 0,
        "additional_state_normalizations": ({"azurerm_linux_virtual_machine.gpu.termination_notification": {"before": None, "after": []}}
                                           if mode == REFRESH_COMPUTED_MODE else {}),
        "reviewed_case_changes": refresh_case_changes(mode, original, expected),
        "created_resources": 0, "deleted_resources": 0, "vm_start_requested": False}
    write_new(directory / "summary.json", summary)
    print(json.dumps(summary, indent=2))


def refresh_apply(directory, supplied_hash):
    summary = load(directory / "summary.json")
    old = window.STATE / summary["retained_window"]
    backend = old / "terraform.tfstate"
    mode = summary.get("state_normalization_mode")
    if (summary["refresh_id"] != directory.name or Path(summary["retained_state_path"]).resolve() != backend.resolve()
            or summary["state"] != "REVIEWED_REFRESH_ONLY_STATE_PLAN" or summary["azure_resource_mutations"] != 0
            or mode not in REFRESH_MODES):
        raise ValueError("Reviewed refresh state scope differs")
    names = {"nic-readback.json"} if mode == REFRESH_COMPUTED_MODE else {"vm-readback.json", "disk-readback.json"}
    if set(summary.get("readback_sha256", {})) != names:
        raise ValueError("Reviewed refresh readback bindings differ")
    bindings = [(directory / "plan.tfplan", supplied_hash), (directory / "plan.tfplan", summary["plan_sha256"]),
        (directory / "plan.json", summary["plan_json_sha256"]), (backend, summary["retained_state_sha256"]),
        (directory / "terraform.tfstate-before", summary["retained_state_sha256"]),
        (directory / "inputs.json", summary["inputs_sha256"]), (old / "inputs.json", summary["inputs_sha256"]),
        (directory / "outputs.json", summary["outputs_sha256"]), (old / "outputs.json", summary["outputs_sha256"]),
        (directory / "operational-inputs.json", summary["operational_inputs_sha256"]),
        (directory / "operational-outputs.json", summary["operational_outputs_sha256"]),
        (window.MODULE / "main.tf", summary["terraform_module_sha256"]), (HERE, summary["resume_controller_sha256"]),
        (HERE.with_name("azure-window.py"), summary["window_controller_sha256"])]
    bindings.extend((directory / name, digest) for name, digest in summary["readback_sha256"].items())
    if any(window.sha(path) != digest for path, digest in bindings):
        raise ValueError("Reviewed refresh plan, backend or source changed")
    if any((directory / name).exists() for name in ("apply.log", "apply-receipt.json", "terraform.tfstate-after")):
        raise ValueError("Refresh operation already attempted; preserve original evidence")
    original_state, original_inputs = load(directory / "terraform.tfstate-before"), load(directory / "inputs.json")
    original = state_resources(original_state)
    inputs, outputs = operational_inputs(original_inputs, original_state)
    if (inputs != load(directory / "operational-inputs.json") or outputs != load(directory / "operational-outputs.json")
            or inputs["expires_at_utc"] != summary["operational_expiry_utc"]):
        raise ValueError("Reviewed operational inputs or outputs differ from current backend")
    plan = saved_plan(directory)
    if plan != load(directory / "plan.json"):
        raise ValueError("Saved refresh binary JSON differs from reviewed original")
    readbacks = {name: load(directory / name) for name in names}
    expected = validate_bound_refresh(plan, original_state, inputs, mode, readbacks)
    if (summary["resource_drift_addresses"] != sorted(row["address"] for row in plan["resource_drift"])
            or summary["reviewed_case_changes"] != refresh_case_changes(mode, original, expected)):
        raise ValueError("Reviewed refresh summary changes differ from saved plan")
    gpu = original["azurerm_linux_virtual_machine.gpu"]
    if gpu["id"] != summary["retained_vm_id"] or gpu["virtual_machine_id"] != summary["retained_vm_uuid"]:
        raise ValueError("Reviewed refresh VM identity differs")
    actual_vm = require_deallocated(gpu["id"], gpu["virtual_machine_id"])
    current_readbacks = refresh_readbacks(mode, original, actual_vm)
    verify_refresh_readback_identity(mode, readbacks, current_readbacks)
    validate_bound_refresh(plan, original_state, inputs, mode, current_readbacks)
    failure, verified = None, False
    try:
        with (directory / "apply.log").open("x") as log:
            window.tf("init", "-input=false", "-reconfigure", f"-backend-config=path={backend}", stdout=log, stderr=subprocess.STDOUT)
            window.tf("apply", "-input=false", str(directory / "plan.tfplan"), stdout=log, stderr=subprocess.STDOUT)
        copy_new(backend, directory / "terraform.tfstate-after")
        refreshed = load(directory / "terraform.tfstate-after")
        if (state_resources(refreshed) != expected or refreshed.get("lineage") != original_state.get("lineage")
                or refreshed.get("serial") != original_state.get("serial", -1) + 1
                or refreshed.get("outputs") != original_state["outputs"]):
            raise ValueError("Actual refreshed backend differs from the validated state-only result")
        actual_vm = require_deallocated(gpu["id"], gpu["virtual_machine_id"])
        current_readbacks = refresh_readbacks(mode, original, actual_vm)
        verify_refresh_readback_identity(mode, readbacks, current_readbacks)
        validate_bound_refresh(plan, original_state, inputs, mode, current_readbacks)
        verified = True
    except BaseException as error:
        failure = type(error).__name__
        raise
    finally:
        write_new(directory / "apply-receipt.json", {"schema_version": 1,
            "state": "VERIFIED_REFRESH_ONLY_STATE_RECONCILIATION" if verified else "FAILED_REFRESH_STATE_RECONCILIATION",
            "timestamp_utc": utcnow().isoformat(), "error_type": failure, "plan_sha256": supplied_hash,
            "state_normalization_mode": mode,
            "before_state_sha256": summary["retained_state_sha256"], "after_state_sha256": window.sha(backend),
            "scope": "LOCAL_TERRAFORM_STATE_RECONCILIATION_ONLY", "azure_resource_mutations": 0,
            "vm_start_requested": False, "deallocation_verified": verified,
            "temporary_resources_retained_for_user_decision": True})


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


def operational_inputs(original_inputs, state):
    """Read the current guard/tags from the backend; preserve original receipts."""
    resources = state_resources(state)
    gpu = resources["azurerm_linux_virtual_machine.gpu"]
    tags = gpu.get("tags", {})
    if (set(tags) != {"project", "window", "expires_at", "workload_sha256", "host_script_sha256"}
            or tags.get("project") != "cc-contract" or tags.get("window") != original_inputs["window_id"]
            or any(resources[address].get("tags") != tags for address in TAGGED)):
        raise ValueError("Current retained workload/expiry tags disagree")
    expires = tags["expires_at"]
    expiry_time(expires)
    if any(not re.fullmatch(r"[a-f0-9]{64}", str(tags[key]))
           for key in ("workload_sha256", "host_script_sha256")):
        raise ValueError("Current retained source tags malformed")
    guard = json.loads(resources["azurerm_logic_app_action_custom.expiry"]["body"])
    if guard.get("expression", {}).get("greaterOrEquals") != ["@ticks(utcNow())", "@ticks('" + expires + "')"]:
        raise ValueError("Current retained guard/tags expiry disagree")
    rules = resources["azurerm_network_security_group.window"].get("security_rule", [])
    if len(rules) != 1:
        raise ValueError("Current retained SSH rule inventory differs")
    current = dict(original_inputs, expires_at_utc=expires,
                   workload_sha256=tags["workload_sha256"], host_script_sha256=tags["host_script_sha256"],
                   ssh_source_cidr=single_ip(rules[0]["source_address_prefix"]))
    outputs = state.get("outputs", {})
    if (set(outputs) != {"expiry", "resource_group", "ssh_address", "vm_id"}
            or outputs["expiry"]["value"] != expires):
        raise ValueError("Current retained backend outputs/expiry disagree")
    verify_outputs(current, outputs, resources)
    if outputs["ssh_address"]["value"] != resources["azurerm_public_ip.window"].get("ip_address"):
        raise ValueError("Current retained SSH output differs from original public IP")
    return current, copy.deepcopy(outputs)


def prior_attempt_budget(paths, campaign, retained_window, gpu, bundle, budget_usd):
    """Carry conservative VM time from preserved, zero-work SSH failures only."""
    if not paths:
        return None
    if len(paths) > 10:
        raise ValueError("Too many prior attempts")
    directories, receipts, used, previous_release = [], [], 0.0, None
    mandatory = ("summary.json", "approved-workload-plan.json", "user-approval.json", "plan.tfplan",
                 "workload-bundle.json", "run-start.json", "start-request.json", "release.json", "run-exit.json",
                 "vm-identity.json", "renewed-guard-readback.json", "run-controller.stderr", "run-phases.jsonl")
    scientific = ("transport", "campaign_id", "images", "planned_jobs", "selected_cases_per_job", "gpu_jobs_parallel",
                  "campaign_spec_sha256", "campaign_harness_sha256", "helper_harness_sha256", "protocol_sha256",
                  "reserved_schedule_sha256")
    for raw_path in paths:
        directory = Path(raw_path)
        if (directory.is_symlink() or not directory.is_dir() or directory.resolve().parent != window.STATE.resolve()
                or str(directory.resolve()) in directories):
            raise ValueError("Distinct preserved prior attempt directories required")
        directory = directory.resolve()
        files = {}
        for name in mandatory:
            path = directory / name
            if not path.is_file() or path.is_symlink() or path.stat().st_size > 8 * 1024 ** 2:
                raise ValueError("Missing or oversized original prior receipt: " + name)
            files[name] = window.sha(path)
        if any((directory / name).exists() for name in ("qualification-session.log", "qualification-session.json", "qualification-exit.json", "collection.json", "startup-ready.json")):
            raise ValueError("A partial scientific or qualified attempt may not reuse this campaign identity")
        if any(path.stat().st_size for path in directory.glob("guest-evidence-*.tar.gz")):
            raise ValueError("Prior attempt contains collected evidence")
        summary, old_bundle = load(directory / "summary.json"), load(directory / "workload-bundle.json")
        previous_allowance = summary.get("cumulative_vm_allowance")
        if (not receipts and summary["max_window_minutes"] != MAX_MINUTES
                or receipts and (not isinstance(previous_allowance, dict)
                    or previous_allowance.get("attempts") != receipts
                    or previous_allowance.get("prior_conservatively_charged_vm_seconds") != used
                    or previous_allowance.get("authorized_total_vm_minutes") != MAX_MINUTES
                    or previous_allowance.get("budget_forecast_total_usd") != budget_usd
                    or summary["max_window_minutes"] > int((MAX_MINUTES * 60 - used) // 60))):
            raise ValueError("Prior cumulative allowance does not preserve the original 90-minute authorization")
        if (summary["campaign_id"] != campaign or summary["retained_window"] != retained_window
                or summary["retained_vm_id"] != gpu["id"] or summary["retained_vm_uuid"] != gpu["virtual_machine_id"]
                or summary["budget_forecast_usd"] != budget_usd or not 0 < summary["max_window_minutes"] <= MAX_MINUTES
                or summary.get("prior_attempt_directories", []) != directories
                or summary != load(directory / "approved-workload-plan.json")
                or summary["plan_sha256"] != files["plan.tfplan"]
                or summary["workload_bundle_sha256"] != files["workload-bundle.json"]
                or any(old_bundle.get(key) != bundle.get(key) for key in scientific)
                or old_bundle.get("planned_jobs") != 140 or old_bundle.get("selected_cases_per_job") != 100
                or old_bundle.get("gpu_jobs_parallel") is not False):
            raise ValueError("Prior attempt identity, authorization or frozen 140-job scope differs")
        validate_approval(load(directory / "user-approval.json"), summary, utcnow())
        qualification = Path(old_bundle["local_qualification_path"])
        if not qualification.is_file() or qualification.is_symlink() or window.sha(qualification) != old_bundle["local_qualification_sha256"]:
            raise ValueError("Original prior source qualification changed")
        qualified = load(qualification)
        for field, filename in (("resume_controller_sha256", "azure-resume-campaign.py"),
                                ("cloud_controller_sha256", "azure-window.py"), ("host_script_sha256", "qualify-host.sh")):
            summary_field = "window_controller_sha256" if field == "cloud_controller_sha256" else field
            if qualified[field] != summary[summary_field]:
                raise ValueError("Prior qualified source differs from its original plan")
            original_source = subprocess.check_output(["git", "-C", str(window.ROOT), "show",
                                  qualified["git_source_commit"] + ":scripts/" + filename], timeout=30)
            if hashlib.sha256(original_source).hexdigest() != qualified[field]:
                raise ValueError("Original published source bytes differ from prior qualification")
        files["original-local-qualification"] = window.sha(qualification)
        identity_rows = load(directory / "vm-identity.json")
        if (not isinstance(identity_rows, list) or len(identity_rows) != 1
                or identity_rows[0].get("type") != "azurerm_linux_virtual_machine"
                or identity_rows[0].get("name") != "gpu" or len(identity_rows[0].get("instances", [])) != 1):
            raise ValueError("Original prior VM identity resource shape differs")
        identity = identity_rows[0]["instances"][0]["attributes"]
        guard = load(directory / "renewed-guard-readback.json")
        if (str(identity.get("id", "")).lower() != gpu["id"].lower()
                or str(identity.get("virtual_machine_id", "")).lower() != gpu["virtual_machine_id"].lower()
                or guard.get("vm_uuid") != gpu["virtual_machine_id"] or guard.get("power_state") != "PowerState/deallocated"):
            raise ValueError("Original prior VM/pre-start deallocation proof differs")
        run, start, release, exit_receipt = (load(directory / name) for name in
                    ("run-start.json", "start-request.json", "release.json", "run-exit.json"))
        def timestamp(value):
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if result.tzinfo is None:
                raise ValueError("Original prior absolute UTC timestamp missing")
            return result
        begin, end = timestamp(start["timestamp_utc"]), timestamp(release["timestamp_utc"])
        if (release.get("power_state") != "PowerState/deallocated" or release.get("retained_os_disk") is not True
                or exit_receipt.get("deallocation_verified") is not True or exit_receipt.get("release_error_type") is not None
                or exit_receipt.get("resources_destroyed_automatically") is not False
                or exit_receipt.get("error_type") != "CalledProcessError"
                or run.get("retained_vm_uuid") != gpu["virtual_machine_id"] or run.get("plan_sha256") != summary["plan_sha256"]
                or not timestamp(run["timestamp_utc"]) <= begin < end <= timestamp(exit_receipt["timestamp_utc"]) <= utcnow()
                or previous_release is not None and begin < previous_release):
            raise ValueError("Prior allocation/confirmed-stop interval or retention proof invalid")
        phases = [json.loads(row) for row in (directory / "run-phases.jsonl").read_text().splitlines()]
        errors = (directory / "run-controller.stderr").read_text()
        if (not any(row.get("phase") == "qualify_collect_release" and row.get("state") == "FAILED"
                    and row.get("error_type") == "CalledProcessError" for row in phases)
                or not ("Connection timed out" in errors or "Connection refused" in errors)):
            raise ValueError("Zero-work first SSH transport failure proof missing")
        elapsed = (end - begin).total_seconds()
        if exit_receipt.get("elapsed_seconds", 0) < elapsed:
            raise ValueError("Prior enclosing interval contradicts VM-time charge")
        used += elapsed
        directories.append(str(directory))
        previous_release = end
        receipts.append({"directory": str(directory), "receipt_sha256": files, "charged_vm_seconds": elapsed,
                         "start_request_utc": start["timestamp_utc"], "confirmed_deallocated_utc": release["timestamp_utc"],
                         "gpu_jobs_started": 0, "zero_work_basis": "FIRST_SSH_TRANSPORT_FAILURE_WITH_NO_SESSION_OR_COLLECTION"})
    remaining_minutes = int((MAX_MINUTES * 60 - used) // 60)
    if remaining_minutes < MIN_START_MINUTES:
        raise ValueError("Insufficient cumulative VM allowance for the qualified campaign")
    return {"schema_version": 1, "scope": "SAME_140_JOB_CAMPAIGN_CUMULATIVE_VM_ALLOWANCE",
            "authorized_total_vm_minutes": MAX_MINUTES, "budget_forecast_total_usd": budget_usd,
            "prior_conservatively_charged_vm_seconds": used, "new_plan_maximum_minutes": remaining_minutes,
            "billing_start_established": False, "attempts": receipts}


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
    original_inputs = load(old / "inputs.json")
    if original_inputs["window_id"] != args.retained_window:
        raise ValueError("Retained window identity differs")
    current_state = load(old / "terraform.tfstate")
    old_inputs, outputs = operational_inputs(original_inputs, current_state)
    original = state_resources(current_state)
    gpu = original["azurerm_linux_virtual_machine.gpu"]
    verify_outputs(old_inputs, outputs, original)
    require_deallocated(gpu["id"], gpu["virtual_machine_id"])
    bundle = window.verify_bundle(args.workload_bundle)
    if bundle.get("transport") != "FIXED_WORK_IR_CAMPAIGN":
        raise ValueError("Only the reviewed fixed-work campaign may resume this VM")
    prior_paths = getattr(args, "prior_attempt", None) or []
    allowance = prior_attempt_budget(prior_paths, args.campaign, args.retained_window, gpu, bundle, args.budget_forecast_usd)
    plan_budget_started = utcnow()
    effective_minutes = min(args.max_window_minutes, allowance["new_plan_maximum_minutes"]) if allowance else args.max_window_minutes
    directory.mkdir(mode=0o700)
    (directory / "workload-bundle.json").write_bytes(args.workload_bundle.read_bytes())
    inputs = dict(old_inputs)
    explicit_expiry = getattr(args, "expires_at_utc", None)
    retry = old_inputs["expires_at_utc"] != original_inputs["expires_at_utc"]
    planned_expiry = explicit_expiry or (old_inputs["expires_at_utc"] if retry and not allowance else
        (plan_budget_started + timedelta(minutes=effective_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    if retry and not allowance and expiry_time(planned_expiry) > expiry_time(old_inputs["expires_at_utc"]):
        raise ValueError("A retry may not extend the original authorized absolute deadline")
    if (expiry_time(planned_expiry) - plan_budget_started).total_seconds() > effective_minutes * 60:
        raise ValueError("Planned expiry exceeds the approved window")
    inputs.update(expires_at_utc=planned_expiry,
                  workload_sha256=window.sha(directory / "workload-bundle.json"),
                  host_script_sha256=window.sha(window.ROOT / "scripts/qualify-host.sh"))
    check_expiry(inputs, utcnow())
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
               "expires_at_utc": inputs["expires_at_utc"], "max_window_minutes": effective_minutes,
               "budget_planning_started_at_utc": plan_budget_started.isoformat(),
               "prior_attempt_directories": [row["directory"] for row in allowance["attempts"]] if allowance else [],
               "cumulative_vm_allowance": allowance,
               "budget_forecast_usd": args.budget_forecast_usd, "workload_bundle_sha256": inputs["workload_sha256"],
               "host_script_sha256": inputs["host_script_sha256"], "retained_state_path": str(old / "terraform.tfstate"),
               "retained_state_sha256": window.sha(old / "terraform.tfstate"), "retained_vm_id": gpu["id"],
               "retained_vm_uuid": gpu["virtual_machine_id"], "old_inputs": old_inputs,
               "retained_original_inputs_sha256": window.sha(old / "inputs.json"),
               "retained_original_outputs_sha256": window.sha(old / "outputs.json"),
               "retry_preserves_absolute_deadline": retry and not allowance,
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
    retained = expected_state.parent
    if (window.sha(retained / "inputs.json") != summary["retained_original_inputs_sha256"]
            or window.sha(retained / "outputs.json") != summary["retained_original_outputs_sha256"]):
        raise ValueError("Original retained input/output receipts changed")
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
    bundle = window.verify_bundle(directory / "workload-bundle.json")
    if bundle.get("transport") != "FIXED_WORK_IR_CAMPAIGN":
        raise ValueError("Reviewed fixed-work campaign required")
    current_state = load(state_path)
    old_inputs, current_outputs = operational_inputs(load(retained / "inputs.json"), current_state)
    if old_inputs != summary["old_inputs"]:
        raise ValueError("Current backend operational inputs differ from the reviewed plan")
    if load(directory / "outputs.json") != current_outputs:
        raise ValueError("Campaign SSH outputs differ from the reviewed retained backend")
    original = state_resources(current_state)
    plan = saved_plan(directory)
    validate_plan(plan, original, inputs, summary["old_inputs"])
    gpu = original["azurerm_linux_virtual_machine.gpu"]
    if summary["retained_vm_uuid"] != gpu["virtual_machine_id"] or summary["retained_vm_id"] != gpu["id"]:
        raise ValueError("Planned retained VM identity changed")
    allowance = prior_attempt_budget(summary.get("prior_attempt_directories", []), summary["campaign_id"],
                    summary["retained_window"], gpu, bundle, summary["budget_forecast_usd"])
    if allowance != summary.get("cumulative_vm_allowance"):
        raise ValueError("Prior attempt budget or original receipt hashes changed")
    if allowance:
        budget_started = datetime.fromisoformat(summary["budget_planning_started_at_utc"].replace("Z", "+00:00"))
        bounded_seconds = (expiry_time(inputs["expires_at_utc"]) - budget_started).total_seconds()
        if (budget_started.tzinfo is None or bounded_seconds <= 0
                or bounded_seconds > allowance["new_plan_maximum_minutes"] * 60
                or allowance["prior_conservatively_charged_vm_seconds"] + bounded_seconds > MAX_MINUTES * 60):
            raise ValueError("Cumulative prior and new VM allowance exceeds the original authorization")
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


def append_startup_observation(directory, name, value):
    with (directory / name).open('a') as output:
        output.write(json.dumps(value) + '\n')
        output.flush()
        os.fsync(output.fileno())


def ssh_probe(directory, outputs, deadline):
    """Only test readiness; never run a GPU command or write guest evidence."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Retained VM startup exceeded 15 minutes")
    started = time.monotonic()
    result, classification = None, None
    try:
        result = subprocess.run(window.ssh_args(directory, outputs) + ["true"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                timeout=min(SSH_ATTEMPT_SECONDS, remaining), check=False)
        message = result.stderr.decode('utf-8', errors='replace').lower()
        if result.returncode == 0:
            classification = 'READY'
        elif 'host key verification failed' in message or 'remote host identification has changed' in message:
            classification = 'HOST_KEY_FAILURE'
        elif 'permission denied' in message or 'no such identity' in message or 'load key' in message:
            classification = 'AUTHENTICATION_FAILURE'
        elif 'connection refused' in message:
            classification = 'CONNECTION_REFUSED'
        elif 'connection timed out' in message:
            classification = 'CONNECT_TIMEOUT'
        else:
            classification = 'SSH_TRANSPORT_FAILURE'
    except subprocess.TimeoutExpired:
        classification = 'PROBE_DEADLINE'
    except BaseException as error:
        classification = type(error).__name__
        raise
    finally:
        append_startup_observation(directory, 'ssh-readiness.jsonl', {
            'timestamp_utc': utcnow().isoformat(), 'monotonic_ns': time.monotonic_ns(),
            'elapsed_seconds': time.monotonic() - started, 'classification': classification,
            'returncode': result.returncode if result is not None else None,
            'guest_command': 'true', 'gpu_command_executed': False})
    if classification in ('HOST_KEY_FAILURE', 'AUTHENTICATION_FAILURE'):
        raise ValueError("Retained SSH readiness failed: " + classification)
    return classification == 'READY'


def start_and_wait(vm_id, uuid, directory=None):
    if directory is None:
        raise ValueError("Private campaign directory required for bounded SSH readiness proof")
    outputs = load(directory / "outputs.json")
    if outputs["vm_id"]["value"].lower() != vm_id.lower():
        raise ValueError("SSH readiness output belongs to another VM")
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    write_new(directory / 'start-request.json',{'timestamp_utc':utcnow().isoformat(),
                  'monotonic_ns':time.monotonic_ns(),'scope':'AZURE_START_REQUEST_BEFORE_CONFIRMED_RUNNING',
                  'billing_start_established':False})
    window.command(["az", "vm", "start", "--ids", vm_id, "--no-wait", "--only-show-errors"], timeout=180)
    while time.monotonic() < deadline:
        view = bounded_az_json(["vm", "get-instance-view", "--ids", vm_id], deadline)
        codes = [row["code"] for row in view["instanceView"]["statuses"]]
        append_startup_observation(directory, 'power-states.jsonl', {'timestamp_utc':utcnow().isoformat(),
                    'monotonic_ns':time.monotonic_ns(),'status_codes':codes,
                    'billing_start_established':False})
        if "PowerState/running" in codes:
            actual = bounded_az_json(["vm", "show", "--ids", vm_id], deadline)
            if str(actual.get("vmId", "")).lower() != uuid.lower():
                raise ValueError("Actual VM UUID changed during startup")
            if ssh_probe(directory, outputs, deadline):
                # A successful probe does not replace the actual retained identity check.
                actual = bounded_az_json(["vm", "show", "--ids", vm_id], deadline)
                view = bounded_az_json(["vm", "get-instance-view", "--ids", vm_id], deadline)
                if str(actual.get("vmId", "")).lower() != uuid.lower():
                    raise ValueError("Actual VM UUID changed during SSH readiness")
                if "PowerState/running" in [row["code"] for row in view["instanceView"]["statuses"]]:
                    write_new(directory / 'startup-ready.json', {'timestamp_utc': utcnow().isoformat(),
                        'monotonic_ns': time.monotonic_ns(), 'retained_vm_uuid': uuid,
                        'power_state': 'PowerState/running', 'ssh_true_succeeded': True,
                        'total_startup_timeout_seconds': START_TIMEOUT_SECONDS,
                        'billing_start_established': False})
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
    parser.add_argument("action", choices=("plan", "run", "refresh-plan", "refresh-apply"))
    parser.add_argument("--campaign", default="fixed-work-1010a")
    parser.add_argument("--retained-window", default="work-sample-1009b")
    parser.add_argument("--refresh-id")
    parser.add_argument("--state-normalization-mode", choices=REFRESH_MODES, default=REFRESH_COMPUTED_MODE)
    parser.add_argument("--workload-bundle", type=Path)
    parser.add_argument("--ssh-source-cidr")
    parser.add_argument("--expires-at-utc", help="Preserve an explicit absolute deadline; retries may never extend it")
    parser.add_argument("--prior-attempt", type=Path, action="append", help="Preserved zero-work SSH failure; carry its VM time within the same 90-minute/15-USD campaign")
    parser.add_argument("--max-window-minutes", type=int, default=MAX_MINUTES)
    parser.add_argument("--budget-forecast-usd", type=float, default=MAX_BUDGET_USD)
    parser.add_argument("--approved-plan-sha256")
    args = parser.parse_args(argv)
    for value in (args.campaign, args.retained_window, *([args.refresh_id] if args.refresh_id else [])):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,20}", value):
            parser.error("Use a lowercase campaign/window identifier")
    native, config = window.STATE / "azure-native-cli-venv/bin/az", window.STATE / "azure-native-cli-config"
    if native.is_file() and (config / "azureProfile.json").is_file():
        os.environ["PATH"] = str(native.parent) + os.pathsep + os.environ["PATH"]
        os.environ["AZURE_CONFIG_DIR"] = str(config)
    if args.action.startswith("refresh-"):
        if not args.refresh_id:
            parser.error("--refresh-id required for state-only reconciliation")
        if args.action == "refresh-plan":
            refresh_plan(args)
        else:
            if not args.approved_plan_sha256:
                parser.error("--approved-plan-sha256 required for the reviewed refresh-only plan")
            refresh_apply(window.STATE / args.refresh_id, args.approved_plan_sha256)
    elif args.action == "plan":
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
