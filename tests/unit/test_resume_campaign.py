"""CPU control-flow fixtures for reuse; these tests never execute Azure."""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("resume_campaign", ROOT / "scripts/azure-resume-campaign.py")
resume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)


class ResumeCampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = self.base / "state"
        self.old = self.state / "work-sample-1009b"
        self.new = self.state / "fixed-work-1010a"
        self.old.mkdir(parents=True)
        self.new.mkdir()
        self.root = self.base / "root"
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "scripts/qualify-host.sh").write_text("CPU fixture only\n")
        self.module = self.base / "terraform"
        self.module.mkdir()
        (self.module / "main.tf").write_text("CPU fixture only\n")
        self.addCleanup(patch.stopall)
        patch.object(resume.window, "STATE", self.state).start()
        patch.object(resume.window, "ROOT", self.root).start()
        patch.object(resume.window, "MODULE", self.module).start()
        self.now = datetime(2026, 10, 10, 1, 0, 0, tzinfo=timezone.utc)
        patch.object(resume, "utcnow", return_value=self.now).start()
        self.uuid = "11111111-2222-3333-4444-555555555555"
        self.vm_id = "/subscriptions/sub/resourceGroups/cc-contract-work-sample-1009b/providers/Microsoft.Compute/virtualMachines/cc-contract-work-sample-1009b"
        self.old_inputs = {"subscription_id": "sub", "window_id": self.old.name,
                           "ssh_public_key": "ssh-ed25519 CPU_FIXTURE", "ssh_source_cidr": "192.0.2.1/32",
                           "expires_at_utc": "2026-10-09T21:38:20Z", "workload_sha256": "a" * 64,
                           "host_script_sha256": "b" * 64}
        self.bundle = {"transport": "FIXED_WORK_IR_CAMPAIGN"}
        self.json(self.new / "workload-bundle.json", self.bundle)
        self.inputs = dict(self.old_inputs, expires_at_utc="2026-10-10T02:29:00Z",
                           workload_sha256=resume.window.sha(self.new / "workload-bundle.json"),
                           host_script_sha256=resume.window.sha(self.root / "scripts/qualify-host.sh"))
        self.original = {address: {"id": "/original/" + address} for address in resume.ADDRESSES}
        self.original["azurerm_linux_virtual_machine.gpu"] = {"id": self.vm_id,
            "virtual_machine_id": self.uuid, "size": "Standard_NCC40ads_H100_v5",
            "secure_boot_enabled": True, "vtpm_enabled": True, "source_image_id": "/pinned/image"}
        for address in resume.TAGGED:
            self.original[address]["tags"] = self.tags(self.old_inputs)
        self.original["azurerm_network_security_group.window"]["security_rule"] = [{"name": "approved-ssh",
            "source_address_prefix": self.old_inputs["ssh_source_cidr"], "destination_port_range": "22"}]
        self.guard = {"type": "If", "expression": {"greaterOrEquals": ["@ticks(utcNow())", "@ticks('" + self.old_inputs["expires_at_utc"] + "')"]},
                      "actions": {"GetState": {"inputs": {"uri": self.vm_id + "/instanceView"}},
                                  "Deallocate": {"inputs": {"uri": self.vm_id + "/deallocate", "method": "POST"}}}}
        self.original["azurerm_logic_app_action_custom.expiry"]["body"] = json.dumps(self.guard)
        self.state_data = {"resources": [{"mode": "managed", "type": address.split(".")[0],
                          "name": address.split(".")[1], "instances": [{"attributes": value}]}
                          for address, value in self.original.items()]}
        self.plan = {"variables": {key: {"value": value} for key, value in self.inputs.items()}, "resource_changes": []}
        for address, before in self.original.items():
            after = copy.deepcopy(before)
            if address in resume.TAGGED:
                after["tags"] = self.tags(self.inputs)
            if address == "azurerm_logic_app_action_custom.expiry":
                body = json.loads(after["body"])
                body["expression"]["greaterOrEquals"][1] = "@ticks('" + self.inputs["expires_at_utc"] + "')"
                after["body"] = json.dumps(body)
            self.plan["resource_changes"].append({"address": address, "change": {
                "actions": ["update"] if after != before else ["no-op"], "before": before,
                "after": after, "after_unknown": {}}})
        self.json(self.old / "terraform.tfstate", self.state_data)
        self.json(self.old / "inputs.json", self.old_inputs)
        self.outputs = {"vm_id": {"value": self.vm_id}, "resource_group": {"value": "cc-contract-" + self.old.name},
                        "ssh_address": {"value": "192.0.2.2"}, "expiry": {"value": self.old_inputs["expires_at_utc"]}}
        self.json(self.old / "outputs.json", self.outputs)
        self.json(self.new / "outputs.json", self.outputs)
        self.json(self.new / "inputs.json", self.inputs)
        (self.old / "id_ed25519").write_text("CPU_FIXTURE_PRIVATE_KEY")
        (self.new / "id_ed25519").symlink_to(self.old / "id_ed25519")
        (self.new / "plan.tfplan").write_bytes(b"CPU_BINARY_PLAN_FIXTURE")
        self.summary = {"schema_version": 1, "campaign_id": self.new.name, "retained_window": self.old.name,
            "planned_at_utc": (self.now - timedelta(minutes=1)).isoformat(),
            "plan_sha256": resume.window.sha(self.new / "plan.tfplan"), "expires_at_utc": self.inputs["expires_at_utc"],
            "max_window_minutes": 90, "budget_forecast_usd": 15,
            "workload_bundle_sha256": self.inputs["workload_sha256"], "host_script_sha256": self.inputs["host_script_sha256"],
            "retained_state_path": str(self.old / "terraform.tfstate"),
            "retained_state_sha256": resume.window.sha(self.old / "terraform.tfstate"),
            "retained_vm_id": self.vm_id, "retained_vm_uuid": self.uuid, "old_inputs": self.old_inputs,
            "terraform_module_sha256": resume.window.sha(self.module / "main.tf"),
            "resume_controller_sha256": resume.window.sha(resume.HERE),
            "window_controller_sha256": resume.window.sha(resume.HERE.with_name("azure-window.py"))}
        self.json(self.new / "summary.json", self.summary)
        self.json(self.new / "approved-workload-plan.json", self.summary)
        self.approval = {"schema_version": 1, "campaign_id": self.new.name, "retained_window": self.old.name,
            "approved": True, "approval_source": "USER_EXPLICIT_APPROVAL", "plan_sha256": self.summary["plan_sha256"],
            "budget_forecast_usd": 15, "max_window_minutes": 90,
            "approved_at_utc": (self.now - timedelta(seconds=30)).isoformat(), "message": "CPU explicit approval fixture"}
        self.json(self.new / "user-approval.json", self.approval)
        self.bundle_check = patch.object(resume.window, "verify_bundle", return_value=self.bundle).start()
        self.saved_check = patch.object(resume, "saved_plan", return_value=self.plan).start()
        self.vm = {"vmId": self.uuid, "tags": self.tags(self.inputs)}

    @staticmethod
    def json(path, value):
        path.write_text(json.dumps(value))

    @staticmethod
    def tags(inputs):
        return {"project": "cc-contract", "window": inputs["window_id"], "expires_at": inputs["expires_at_utc"],
                "workload_sha256": inputs["workload_sha256"], "host_script_sha256": inputs["host_script_sha256"]}

    def row(self, address):
        return next(row for row in self.plan["resource_changes"] if row["address"] == address)["change"]

    def test_update_only_plan_accepts_tag_expiry_and_explicit_single_ip(self):
        self.assertEqual(len(resume.validate_plan(self.plan, self.original, self.inputs, self.old_inputs)), 13)
        inputs = dict(self.inputs, ssh_source_cidr="198.51.100.2/32")
        plan = copy.deepcopy(self.plan)
        plan["variables"]["ssh_source_cidr"]["value"] = inputs["ssh_source_cidr"]
        row = next(row for row in plan["resource_changes"] if row["address"] == "azurerm_network_security_group.window")
        row["change"]["after"]["security_rule"][0]["source_address_prefix"] = inputs["ssh_source_cidr"]
        resume.validate_plan(plan, self.original, inputs, self.old_inputs)
        with self.assertRaisesRegex(ValueError, "IPv4 /32"):
            resume.single_ip("198.51.100.0/24")

    def test_replacements_missing_extra_addresses_and_vm_security_changes_rejected(self):
        for mutation in (lambda p: p["resource_changes"].pop(),
                         lambda p: p["resource_changes"].append(copy.deepcopy(p["resource_changes"][0])),
                         lambda p: p["resource_changes"][0]["change"].update(actions=["delete", "create"])):
            plan = copy.deepcopy(self.plan); mutation(plan)
            with self.assertRaises(ValueError):
                resume.validate_plan(plan, self.original, self.inputs, self.old_inputs)
        for key, value in (("size", "other"), ("secure_boot_enabled", False), ("source_image_id", "/different")):
            plan = copy.deepcopy(self.plan)
            row = next(row for row in plan["resource_changes"] if row["address"] == "azurerm_linux_virtual_machine.gpu")
            row["change"]["after"][key] = value
            with self.assertRaisesRegex(ValueError, "Unapproved resource field"):
                resume.validate_plan(plan, self.original, self.inputs, self.old_inputs)

    def test_guard_body_edit_unknown_values_and_drift_rejected(self):
        original_plan = copy.deepcopy(self.plan)
        body = json.loads(self.row("azurerm_logic_app_action_custom.expiry")["after"]["body"])
        body["actions"]["Deallocate"]["inputs"]["uri"] = "/wrong/vm/deallocate"
        self.row("azurerm_logic_app_action_custom.expiry")["after"]["body"] = json.dumps(body)
        with self.assertRaisesRegex(ValueError, "Only the expiry timestamp"):
            resume.validate_plan(self.plan, self.original, self.inputs, self.old_inputs)
        self.plan = copy.deepcopy(original_plan)
        self.row("azurerm_linux_virtual_machine.gpu")["after_unknown"] = {"id": True}
        with self.assertRaisesRegex(ValueError, "Unknown planned"):
            resume.validate_plan(self.plan, self.original, self.inputs, self.old_inputs)
        self.plan = original_plan
        self.plan["resource_drift"] = [{"address": "unexpected"}]
        with self.assertRaisesRegex(ValueError, "drift"):
            resume.validate_plan(self.plan, self.original, self.inputs, self.old_inputs)

    def test_approval_budget_hash_message_and_timing_gate_precede_cloud_calls(self):
        for key, value in (("approved", False), ("plan_sha256", "0" * 64), ("budget_forecast_usd", 20),
                           ("max_window_minutes", 120), ("message", ""),
                           ("approved_at_utc", (self.now + timedelta(seconds=1)).isoformat())):
            approval = dict(self.approval, **{key: value})
            self.json(self.new / "user-approval.json", approval)
            with patch.object(resume.window, "az_json") as cloud:
                with self.assertRaises(ValueError):
                    resume.run_campaign(self.new, self.summary["plan_sha256"])
                cloud.assert_not_called()

    def test_changed_bundle_backend_and_saved_variables_rejected_without_cloud(self):
        for path in (self.new / "workload-bundle.json", self.old / "terraform.tfstate"):
            original = path.read_bytes(); path.write_bytes(original + b" ")
            with patch.object(resume.window, "az_json") as cloud:
                with self.assertRaises(ValueError):
                    resume.verify_run(self.new, self.summary["plan_sha256"])
                cloud.assert_not_called()
            path.write_bytes(original)
        self.plan["variables"]["expires_at_utc"]["value"] = self.old_inputs["expires_at_utc"]
        with self.assertRaisesRegex(ValueError, "Saved plan variables"):
            resume.verify_run(self.new, self.summary["plan_sha256"])

    def test_same_actual_uuid_and_deallocated_state_required(self):
        def az(*args):
            if args[:2] == ("vm", "show"):
                return self.vm
            return {"instanceView": {"statuses": [{"code": "PowerState/running"}]}}
        with patch.object(resume.window, "az_json", side_effect=az):
            with self.assertRaisesRegex(ValueError, "deallocated"):
                resume.require_deallocated(self.vm_id, self.uuid)
            with self.assertRaisesRegex(ValueError, "UUID changed"):
                resume.require_deallocated(self.vm_id, "different")

    def test_actual_expiry_workflow_must_match_and_be_enabled_before_start(self):
        guard = json.loads(self.row("azurerm_logic_app_action_custom.expiry")["after"]["body"])
        actual = {"properties": {"state": "Enabled", "definition": {"actions": {"ExpiryGuard": guard},
            "triggers": {"ExpiryTick": {"type": "Recurrence", "recurrence": {"frequency": "Minute", "interval": 1}}}}}}
        with patch.object(resume, "require_deallocated", return_value=self.vm), \
             patch.object(resume.window, "az_json", return_value=actual):
            resume.verify_guard_and_tags(self.new, self.plan, self.uuid)
            (self.new / "renewed-guard-readback.json").unlink()
            actual["properties"]["definition"]["actions"]["ExpiryGuard"] = self.guard
            with self.assertRaisesRegex(ValueError, "Actual Azure expiry guard"):
                resume.verify_guard_and_tags(self.new, self.plan, self.uuid)
            actual["properties"]["state"] = "Disabled"
            with self.assertRaisesRegex(ValueError, "not enabled"):
                resume.verify_guard_and_tags(self.new, self.plan, self.uuid)

    def test_startup_failure_and_apply_failure_always_release_before_exit_receipt(self):
        for phase in ("apply", "start", "guard"):
            with self.subTest(phase=phase):
                for name in ("run-start.json", "run-exit.json", "apply.log", "tfstate-after-apply.json", "vm-identity.json"):
                    (self.new / name).unlink(missing_ok=True)
                events = []
                def tf(*args, **kwargs):
                    events.append(args[0])
                    if phase == "apply" and args[0] == "apply":
                        raise RuntimeError("CPU apply failure fixture")
                def release(directory):
                    self.assertFalse((directory / "run-exit.json").exists())
                    events.append("release")
                with patch.object(resume, "require_deallocated", return_value=self.vm), \
                     patch.object(resume.window, "tf", side_effect=tf), \
                     patch.object(resume, "verify_guard_and_tags", side_effect=RuntimeError("CPU guard fixture") if phase == "guard" else None), \
                     patch.object(resume, "start_and_wait", side_effect=RuntimeError("CPU start fixture") if phase == "start" else None), \
                     patch.object(resume.window, "release", side_effect=release) as stop, \
                     patch.object(resume.window, "run_phase") as qualify:
                    with self.assertRaises(RuntimeError):
                        resume.run_campaign(self.new, self.summary["plan_sha256"])
                    stop.assert_called_once_with(self.new)
                    qualify.assert_not_called()
                self.assertEqual(events[-1], "release")
                self.assertFalse(resume.load(self.new / "run-exit.json")["resources_destroyed_automatically"])

    def test_success_orders_apply_guard_start_qualify_and_confirmed_stop(self):
        events = []
        def qualify(*args):
            events.append("qualify")
            self.json(self.new / "release.json", {"power_state": "PowerState/deallocated"})
        with patch.object(resume, "require_deallocated", side_effect=lambda *a: events.append("deallocated") or self.vm), \
             patch.object(resume.window, "tf", side_effect=lambda *a, **k: events.append(a[0])), \
             patch.object(resume, "verify_guard_and_tags", side_effect=lambda *a: events.append("guard")), \
             patch.object(resume, "start_and_wait", side_effect=lambda *a: events.append("start")), \
             patch.object(resume.window, "run_phase", side_effect=qualify), \
             patch.object(resume.window, "release") as stop:
            resume.run_campaign(self.new, self.summary["plan_sha256"])
            stop.assert_not_called()
        self.assertEqual(events, ["deallocated", "init", "apply", "guard", "start", "qualify", "deallocated"])
        self.assertEqual(resume.load(self.new / "outputs.json")["expiry"]["value"], self.inputs["expires_at_utc"])
        self.assertTrue((self.new / "id_ed25519").is_symlink())

    def test_existing_explicit_instruction_binding_does_not_invent_human_timestamp(self):
        approval=resume.load(self.new/'user-approval.json')
        approval.update(approved_at_utc=None,binding_source='EXISTING_EXPLICIT_USER_INSTRUCTION',
                        plan_bound_at_utc=self.now.isoformat(),user_has_not_seen_plan_sha256=True)
        resume.validate_approval(approval,self.summary,self.now)
        for field,value in [('binding_source','AGENT_DECISION'),('user_has_not_seen_plan_sha256',False),
                            ('plan_bound_at_utc','2026-10-10T02:00:00Z')]:
            with self.subTest(field=field):
                changed=dict(approval);changed[field]=value
                with self.assertRaises(ValueError):
                    resume.validate_approval(changed,self.summary,self.now)

    def test_start_request_and_power_observations_are_saved_without_billing_claim(self):
        running={'instanceView':{'statuses':[{'code':'PowerState/running'}]}}
        with patch.object(resume.window,'command'), \
             patch.object(resume,'bounded_az_json',side_effect=[running,{'vmId':self.uuid}]):
            resume.start_and_wait(self.vm_id,self.uuid,self.new)
        request=resume.load(self.new/'start-request.json')
        observations=[json.loads(row) for row in (self.new/'power-states.jsonl').read_text().splitlines()]
        self.assertFalse(request['billing_start_established'])
        self.assertFalse(observations[0]['billing_start_established'])
        self.assertIn('PowerState/running',observations[0]['status_codes'])
        self.assertLessEqual(request['monotonic_ns'],observations[0]['monotonic_ns'])

    def test_expiry_and_startup_poll_are_bounded(self):
        for expiry in (self.old_inputs["expires_at_utc"], "2026-10-10T02:14:59Z", "2026-10-10T02:30:01Z"):
            with self.assertRaises(ValueError):
                resume.check_expiry(dict(self.inputs, expires_at_utc=expiry), self.now)
        with patch.object(resume.window, "command") as command, \
             patch.object(resume.time, "monotonic", side_effect=[0, resume.START_TIMEOUT_SECONDS + 1]), \
             patch.object(resume.window, "az_json") as cloud:
            with self.assertRaises(TimeoutError):
                resume.start_and_wait(self.vm_id, self.uuid)
            self.assertIn("--no-wait", command.call_args.args[0])
            cloud.assert_not_called()
        with patch.object(resume.time, "monotonic", return_value=10), \
             patch.object(resume.subprocess, "check_output", return_value=b'{"ok": true}') as execute:
            self.assertTrue(resume.bounded_az_json(["vm", "show"], 12)["ok"])
            self.assertEqual(execute.call_args.kwargs["timeout"], 2)

    def test_plan_uses_existing_backend_without_compute_mutation_or_old_file_changes(self):
        self.new.rename(self.state / "unused-fixture")
        bundle_path = self.base / "bundle.json"
        self.json(bundle_path, self.bundle)
        old_bytes = {path.name: path.read_bytes() for path in self.old.iterdir() if path.is_file()}
        args = argparse.Namespace(campaign=self.new.name, retained_window=self.old.name,
            max_window_minutes=90, budget_forecast_usd=15, workload_bundle=bundle_path,
            ssh_source_cidr=None)
        calls = []
        def tf(*values, **kwargs):
            calls.append(values)
            if values[0] == "plan":
                (self.new / "plan.tfplan").write_bytes(b"CPU_BINARY_PLAN_FIXTURE")
                inputs = resume.load(self.new / "inputs.json")
                self.plan["variables"] = {key: {"value": value} for key, value in inputs.items()}
                for row in self.plan["resource_changes"]:
                    if row["address"] in resume.TAGGED:
                        row["change"]["after"]["tags"] = self.tags(inputs)
                    if row["address"] == "azurerm_logic_app_action_custom.expiry":
                        body = json.loads(row["change"]["after"]["body"])
                        body["expression"]["greaterOrEquals"][1] = "@ticks('" + inputs["expires_at_utc"] + "')"
                        row["change"]["after"]["body"] = json.dumps(body)
        with patch.object(resume, "require_deallocated", return_value=self.vm), \
             patch.object(resume.window, "tf", side_effect=tf), \
             patch.object(resume.window, "command") as mutate, \
             patch("builtins.print"):
            resume.plan_campaign(args)
            mutate.assert_not_called()
        self.assertEqual([call[0] for call in calls], ["init", "plan"])
        self.assertIn("-backend-config=path=" + str(self.old / "terraform.tfstate"), calls[0])
        self.assertEqual(old_bytes, {path.name: path.read_bytes() for path in self.old.iterdir() if path.is_file()})
        self.assertEqual(resume.load(self.new / "summary.json")["created_resources"], 0)
        self.assertFalse((self.new / "user-approval.json").exists())
        self.assertTrue((self.new / "id_ed25519").is_symlink())


if __name__ == "__main__":
    unittest.main()
