"""CPU evidence fixtures for one retained OS disk ARM-ID casing refresh."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("disk_case_refresh_fixtures", ROOT / "tests/unit/test_refresh_state.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
resume = fixtures.resume
VM = "azurerm_linux_virtual_machine.gpu"
MODE = "os-disk-arm-id-case"


class RefreshDiskIdCaseTests(unittest.TestCase):
    json = staticmethod(fixtures.RefreshStateTests.json)
    tags = staticmethod(fixtures.RefreshStateTests.tags)

    def setUp(self):
        fixtures.RefreshStateTests.setUp(self)
        self.original = copy.deepcopy(self.expected)
        self.current_inputs = dict(self.old_inputs, expires_at_utc="2026-10-10T01:59:00Z",
                                   workload_sha256="c" * 64)
        for address in resume.TAGGED:
            self.original[address]["tags"] = self.tags(self.current_inputs)
        original_state = resume.load(self.old / "terraform.tfstate")
        self.assertEqual(original_state["outputs"]["expiry"]["value"], self.old_inputs["expires_at_utc"])
        body = json.loads(self.original["azurerm_logic_app_action_custom.expiry"]["body"])
        body["expression"]["greaterOrEquals"][1] = "@ticks('" + self.current_inputs["expires_at_utc"] + "')"
        self.original["azurerm_logic_app_action_custom.expiry"]["body"] = json.dumps(body)
        self.disk_id = "/subscriptions/sub/resourceGroups/cc-contract-work-sample-1009b/providers/Microsoft.Compute/disks/original-os"
        self.read_disk_id = self.disk_id.replace("cc-contract-work-sample-1009b/", "CC-CONTRACT-WORK-SAMPLE-1009B/")
        gpu = self.original[VM]
        gpu.update(os_managed_disk_id=self.disk_id, os_disk=[{
            "id": self.disk_id, "name": "original-os", "caching": "ReadWrite", "disk_size_gb": 128}])
        self.state_data.update(serial=24)
        self.state_data["outputs"] = copy.deepcopy(self.outputs)
        self.state_data["outputs"]["expiry"]["value"] = self.current_inputs["expires_at_utc"]
        for row in self.state_data["resources"]:
            row["instances"][0]["attributes"] = copy.deepcopy(self.original[row["type"] + "." + row["name"]])
        self.json(self.old / "terraform.tfstate", self.state_data)
        self.vm = {"id": self.vm_id, "vmId": self.uuid, "tags": self.tags(self.current_inputs),
                   "storageProfile": {"osDisk": {"managedDisk": {"id": self.read_disk_id}}}}
        self.disk = {"id": self.disk_id, "name": "original-os", "managedBy": self.vm_id,
                     "uniqueId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}
        self.expected = copy.deepcopy(self.original)
        self.expected[VM]["os_managed_disk_id"] = self.read_disk_id
        self.expected[VM]["os_disk"][0]["id"] = self.read_disk_id
        plan_outputs = {name: dict(row, sensitive=False) for name, row in self.state_data["outputs"].items()}
        resources = [{"address": address, "mode": "managed", "type": address.split(".")[0],
            "name": address.split(".")[1], "provider_name": "registry.terraform.io/hashicorp/azurerm", "values": value}
            for address, value in self.expected.items()]
        variables = dict(self.current_inputs, confidential_image_id=self.original[VM]["source_image_id"], model_container_scope="")
        self.plan = {"terraform_version": "1.12.2", "complete": True, "errored": False,
            "variables": {key: {"value": value} for key, value in variables.items()},
            "planned_values": {"root_module": {}, "outputs": plan_outputs},
            "prior_state": {"values": {"root_module": {"resources": resources}, "outputs": plan_outputs}},
            "resource_drift": [{"address": VM, "change": {"actions": ["update"], "before": self.original[VM],
                "after": self.expected[VM], "after_unknown": {}}}],
            "output_changes": {name: {"actions": ["no-op"], "before": row["value"], "after": row["value"], "after_unknown": False}
                for name, row in self.state_data["outputs"].items()}}
        self.saved_check.return_value = self.plan

    def validate(self, plan=None, vm=None, disk=None):
        return resume.validate_refresh_plan(self.plan if plan is None else plan, self.state_data, self.current_inputs,
            normalization_mode=MODE, vm_readback=self.vm if vm is None else vm,
            disk_readback=self.disk if disk is None else disk)

    def azure_read(self, *args):
        self.assertEqual(args, ("disk", "show", "--ids", self.disk_id))
        return copy.deepcopy(self.disk)

    def make_plan(self):
        calls = []
        def tf(*args, **kwargs):
            calls.append(args)
            if args[0] == "plan":
                (self.refresh / "plan.tfplan").write_bytes(b"CPU_OS_DISK_CASE_REFRESH_ONLY_FIXTURE")
        args = argparse.Namespace(retained_window=self.old.name, refresh_id=self.refresh.name, state_normalization_mode=MODE)
        with patch.object(resume, "require_deallocated", return_value=self.vm), \
             patch.object(resume.window, "az_json", side_effect=self.azure_read), \
             patch.object(resume.window, "tf", side_effect=tf), patch("builtins.print"):
            resume.refresh_plan(args)
        return calls

    def test_exact_two_rg_case_paths_preserve_all_13_values_and_outputs(self):
        self.assertEqual(self.validate(), self.expected)
        unchanged = copy.deepcopy(self.expected)
        unchanged[VM]["os_managed_disk_id"] = self.disk_id
        unchanged[VM]["os_disk"][0]["id"] = self.disk_id
        self.assertEqual(unchanged, self.original)
        self.assertEqual(len(self.expected), 13)
        self.assertEqual(self.plan["prior_state"]["values"]["outputs"], self.plan["planned_values"]["outputs"])
        plan = copy.deepcopy(self.plan)
        plan["resource_changes"] = [{"address": address, "change": {
            "actions": ["no-op"], "before": value, "after": value, "after_unknown": {}}}
            for address, value in self.expected.items()]
        self.assertEqual(self.validate(plan), self.expected)

    def test_disk_replacement_and_case_changes_outside_rg_are_rejected(self):
        for changed_id in (self.read_disk_id.replace("original-os", "replacement-os"),
                           self.read_disk_id.replace("/subscriptions/", "/Subscriptions/"),
                           self.read_disk_id.replace("Microsoft.Compute", "microsoft.compute"),
                           self.read_disk_id.replace("original-os", "ORIGINAL-OS")):
            with self.subTest(changed_id=changed_id):
                vm = copy.deepcopy(self.vm)
                vm["storageProfile"]["osDisk"]["managedDisk"]["id"] = changed_id
                with self.assertRaises(ValueError):
                    self.validate(vm=vm)

    def test_live_vm_uuid_disk_attachment_and_readback_identity_are_required(self):
        for key, value in (("vmId", "other-uuid"), ("id", "/other/vm"), ("storageProfile", {})):
            with self.subTest(vm_field=key):
                with self.assertRaises(ValueError):
                    self.validate(vm=dict(self.vm, **{key: value}))
        for key, value in (("id", self.disk_id + "-replacement"), ("managedBy", "/other/vm"),
                           ("name", "replacement-os")):
            with self.subTest(disk_field=key):
                with self.assertRaises(ValueError):
                    self.validate(disk=dict(self.disk, **{key: value}))
        with self.assertRaises(ValueError):
            resume.validate_refresh_plan(self.plan, self.state_data, self.current_inputs, normalization_mode=MODE)

    def test_only_two_paths_single_drift_and_no_resource_mutation_are_permitted(self):
        mutations = (lambda p: p["resource_drift"].clear(),
            lambda p: p["resource_drift"].append(copy.deepcopy(p["resource_drift"][0])),
            lambda p: p["resource_drift"][0]["change"]["after"].update(secure_boot_enabled=False),
            lambda p: p["resource_drift"][0]["change"]["after"]["os_disk"][0].update(caching="None"),
            lambda p: p["resource_drift"][0]["change"]["after"].update(os_managed_disk_id=self.disk_id),
            lambda p: p["resource_drift"][0]["change"].update(after_unknown={"id": True}),
            lambda p: p["resource_drift"][0].update(previous_address="moved"),
            lambda p: p.update(resource_changes=[{"address": VM, "change": {"actions": ["update"]}}]))
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                plan = copy.deepcopy(self.plan); mutation(plan)
                with self.assertRaises(ValueError): self.validate(plan)

    def test_changed_inputs_outputs_and_silent_other_resources_are_rejected(self):
        mutations = (lambda p: p["variables"]["expires_at_utc"].update(value=self.old_inputs["expires_at_utc"]),
            lambda p: p["output_changes"]["expiry"].update(after="later"),
            lambda p: p["planned_values"]["outputs"].pop("vm_id"),
            lambda p: p["prior_state"]["values"]["root_module"]["resources"][0]["values"].update(id="/different/resource"),
            lambda p: p["planned_values"].update(root_module={"resources": p["prior_state"]["values"]["root_module"]["resources"]}))
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                plan = copy.deepcopy(self.plan); mutation(plan)
                with self.assertRaises(ValueError): self.validate(plan)

    def test_regular_campaign_validator_still_rejects_case_drift(self):
        self.plan["resource_changes"] = [{"address": address, "change": {
            "actions": ["no-op"], "before": value, "after": value, "after_unknown": {}}}
            for address, value in self.expected.items()]
        with self.assertRaisesRegex(ValueError, "drift"):
            resume.validate_plan(self.plan, self.original, self.current_inputs, self.current_inputs)
        with self.assertRaises(ValueError):
            resume.validate_refresh_plan(self.plan, self.state_data, self.current_inputs, self.nic)

    def test_read_only_plan_preserves_original_bytes_and_uses_current_backend_inputs(self):
        before = {p.name: p.read_bytes() for p in self.old.iterdir() if p.is_file()}
        with patch.object(resume.window, "command") as mutation:
            calls = self.make_plan()
            mutation.assert_not_called()
        self.assertEqual([call[0] for call in calls], ["init", "plan"])
        self.assertIn("-refresh-only", calls[1])
        self.assertIn(f"-var-file={self.refresh / 'operational-inputs.json'}", calls[1])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.old.iterdir() if p.is_file()})
        self.assertEqual((self.refresh / "inputs.json").read_bytes(), before["inputs.json"])
        self.assertEqual((self.refresh / "outputs.json").read_bytes(), before["outputs.json"])
        self.assertEqual(resume.load(self.refresh / "operational-inputs.json"), self.current_inputs)
        self.assertEqual(resume.load(self.refresh / "operational-outputs.json"), self.state_data["outputs"])
        summary = resume.load(self.refresh / "summary.json")
        self.assertEqual(summary["state_normalization_mode"], MODE)
        self.assertFalse(summary["vm_start_requested"])
        for name in ("vm-readback.json", "disk-readback.json"):
            self.assertEqual(summary["readback_sha256"][name], resume.window.sha(self.refresh / name))

    def test_apply_requires_unchanged_originals_backend_operational_proofs_and_sources(self):
        self.make_plan()
        digest = resume.window.sha(self.refresh / "plan.tfplan")
        paths = (self.refresh / "plan.tfplan", self.old / "terraform.tfstate", self.old / "inputs.json",
                 self.old / "outputs.json", self.refresh / "operational-inputs.json", self.refresh / "operational-outputs.json",
                 self.refresh / "vm-readback.json", self.refresh / "disk-readback.json", self.module / "main.tf")
        for path in paths:
            with self.subTest(path=path.name):
                before = path.read_bytes(); path.write_bytes(before + b" ")
                try:
                    with patch.object(resume.window, "az_json") as cloud, patch.object(resume.window, "tf") as tf:
                        with self.assertRaises(ValueError): resume.refresh_apply(self.refresh, digest)
                        cloud.assert_not_called(); tf.assert_not_called()
                finally:
                    path.write_bytes(before)

    def test_missing_or_unreviewed_plan_is_rejected_before_apply(self):
        self.make_plan()
        digest = resume.window.sha(self.refresh / "plan.tfplan")
        summary_path = self.refresh / "summary.json"
        before = summary_path.read_bytes()
        summary = resume.load(summary_path)
        summary["state"] = "UNQUALIFIED_CPU_CASE_PROTOTYPE"
        self.json(summary_path, summary)
        with patch.object(resume.window, "az_json") as cloud, patch.object(resume.window, "tf") as tf:
            with self.assertRaises(ValueError): resume.refresh_apply(self.refresh, digest)
            cloud.assert_not_called(); tf.assert_not_called()
        summary_path.write_bytes(before)
        with patch.object(resume.window, "az_json") as cloud, patch.object(resume.window, "tf") as tf:
            with self.assertRaises(ValueError): resume.refresh_apply(self.refresh, "0" * 64)
            cloud.assert_not_called(); tf.assert_not_called()
        summary_path.unlink()
        try:
            with patch.object(resume.window, "az_json") as cloud, patch.object(resume.window, "tf") as tf:
                with self.assertRaises((ValueError, FileNotFoundError)):
                    resume.refresh_apply(self.refresh, digest)
                cloud.assert_not_called(); tf.assert_not_called()
        finally:
            summary_path.write_bytes(before)

    def test_case_only_state_apply_retains_uuid_outputs_and_deallocated_vm(self):
        self.make_plan()
        calls = []
        def tf(*args, **kwargs):
            calls.append(args)
            if args[0] == "apply":
                state = copy.deepcopy(self.state_data)
                state["serial"] += 1
                for row in state["resources"]:
                    row["instances"][0]["attributes"] = copy.deepcopy(self.expected[row["type"] + "." + row["name"]])
                self.json(self.old / "terraform.tfstate", state)
        with patch.object(resume, "require_deallocated", return_value=self.vm) as off, \
             patch.object(resume.window, "az_json", side_effect=self.azure_read), \
             patch.object(resume.window, "tf", side_effect=tf), patch.object(resume.window, "command") as mutation:
            resume.refresh_apply(self.refresh, resume.window.sha(self.refresh / "plan.tfplan"))
            mutation.assert_not_called()
        self.assertEqual(off.call_count, 2)
        self.assertEqual([call[0] for call in calls], ["init", "apply"])
        result = resume.load(self.old / "terraform.tfstate")
        self.assertEqual(result["outputs"], self.state_data["outputs"])
        self.assertEqual(result["lineage"], self.state_data["lineage"])
        self.assertEqual(result["serial"], 25)
        self.assertEqual(resume.state_resources(result), self.expected)
        receipt = resume.load(self.refresh / "apply-receipt.json")
        self.assertEqual(receipt["state"], "VERIFIED_REFRESH_ONLY_STATE_RECONCILIATION")
        self.assertTrue(receipt["deallocation_verified"])
        self.assertFalse(receipt["vm_start_requested"])

    def test_live_disk_replacement_between_review_and_apply_blocks_tf(self):
        self.make_plan()
        with patch.object(resume, "require_deallocated", return_value=self.vm), \
             patch.object(resume.window, "az_json", return_value=dict(self.disk, managedBy="/different/vm")), \
             patch.object(resume.window, "tf") as tf:
            with self.assertRaises(ValueError):
                resume.refresh_apply(self.refresh, resume.window.sha(self.refresh / "plan.tfplan"))
            tf.assert_not_called()

    def test_disk_unique_id_is_required_and_same_name_replacement_blocks_apply(self):
        for value in (None, "", "malformed-uuid"):
            with self.subTest(unique_id=value):
                disk = copy.deepcopy(self.disk)
                if value is None:
                    disk.pop("uniqueId")
                else:
                    disk["uniqueId"] = value
                with self.assertRaises(ValueError):
                    self.validate(disk=disk)
        self.make_plan()
        replacement = dict(self.disk, uniqueId="ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee")
        with patch.object(resume, "require_deallocated", return_value=self.vm), \
             patch.object(resume.window, "az_json", return_value=replacement), \
             patch.object(resume.window, "tf") as tf:
            with self.assertRaises(ValueError):
                resume.refresh_apply(self.refresh, resume.window.sha(self.refresh / "plan.tfplan"))
            tf.assert_not_called()

    def test_post_apply_output_mutation_preserves_evidence_and_records_failure(self):
        self.make_plan()
        before = (self.old / "terraform.tfstate").read_bytes()
        def tf(*args, **kwargs):
            if args[0] == "apply":
                state = copy.deepcopy(self.state_data)
                state["serial"] += 1
                for row in state["resources"]:
                    row["instances"][0]["attributes"] = copy.deepcopy(self.expected[row["type"] + "." + row["name"]])
                state["outputs"]["expiry"]["value"] = "unreviewed-expiry"
                self.json(self.old / "terraform.tfstate", state)
        with patch.object(resume, "require_deallocated", return_value=self.vm), \
             patch.object(resume.window, "az_json", side_effect=self.azure_read), \
             patch.object(resume.window, "tf", side_effect=tf), patch.object(resume.window, "command") as mutation:
            with self.assertRaisesRegex(ValueError, "Actual refreshed backend differs"):
                resume.refresh_apply(self.refresh, resume.window.sha(self.refresh / "plan.tfplan"))
            mutation.assert_not_called()
        self.assertEqual((self.refresh / "terraform.tfstate-before").read_bytes(), before)
        self.assertTrue((self.refresh / "terraform.tfstate-after").exists())
        receipt = resume.load(self.refresh / "apply-receipt.json")
        self.assertEqual(receipt["state"], "FAILED_REFRESH_STATE_RECONCILIATION")
        self.assertFalse(receipt["deallocation_verified"])
        self.assertFalse(receipt["vm_start_requested"])
        self.assertTrue(receipt["temporary_resources_retained_for_user_decision"])


if __name__ == "__main__":
    unittest.main()
