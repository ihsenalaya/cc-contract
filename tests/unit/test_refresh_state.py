"""CPU fixtures for strict retained-state refresh; never invoke Azure or Terraform."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("resume_fixtures", ROOT / "tests/unit/test_resume_campaign.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
resume = fixtures.resume


class RefreshStateTests(unittest.TestCase):
    json = staticmethod(fixtures.ResumeCampaignTests.json)
    tags = staticmethod(fixtures.ResumeCampaignTests.tags)

    def setUp(self):
        fixtures.ResumeCampaignTests.setUp(self)
        self.refresh = self.state / "state-refresh-1010a"
        self.original["azurerm_linux_virtual_machine.gpu"]["termination_notification"] = None
        self.original["azurerm_logic_app_workflow.expiry"]["identity"] = [{
            "identity_ids": None, "principal_id": "original-principal", "tenant_id": "original-tenant", "type": "SystemAssigned"}]
        self.original["azurerm_network_interface.window"].update(name="original-nic", resource_group_name="original-rg",
            dns_servers=None, mac_address="", virtual_machine_id="")
        self.original["azurerm_public_ip.window"].update(ip_tags=None, zones=None)
        self.original["azurerm_role_definition.expiry"]["permissions"] = [{"actions": ["original-read", "original-deallocate"],
            "not_actions": None, "data_actions": None, "not_data_actions": None}]
        vnet = self.original["azurerm_virtual_network.window"]
        vnet.update(subnet=[])
        subnet = self.original["azurerm_subnet.window"]
        subnet.update(id=vnet["id"] + "/subnets/gpu", name="gpu", address_prefixes=["10.239.0.0/24"],
            network_security_group_id="", service_endpoint_policy_ids=None, default_outbound_access_enabled=True,
            delegation=[], private_endpoint_network_policies="Disabled", private_link_service_network_policies_enabled=True,
            route_table_id="", service_endpoint=[])
        nsg_id = self.original["azurerm_network_security_group.window"]["id"]
        self.original["azurerm_subnet_network_security_group_association.window"].update(subnet_id=subnet["id"], network_security_group_id=nsg_id)
        self.state_data.update(serial=14, lineage="original-state-lineage", outputs=copy.deepcopy(self.outputs))
        self.json(self.old / "terraform.tfstate", self.state_data)
        nic = self.original["azurerm_network_interface.window"]
        self.nic = {"id": nic["id"], "name": nic["name"], "resourceGroup": nic["resource_group_name"],
            "virtualMachine": {"id": self.vm_id}, "macAddress": "7C-1E-52-C8-B3-E6"}
        self.expected = copy.deepcopy(self.original)
        self.expected["azurerm_linux_virtual_machine.gpu"]["termination_notification"] = []
        self.expected["azurerm_logic_app_workflow.expiry"]["identity"][0]["identity_ids"] = []
        self.expected["azurerm_network_interface.window"].update(dns_servers=[], mac_address=self.nic["macAddress"], virtual_machine_id=self.vm_id)
        self.expected["azurerm_public_ip.window"].update(ip_tags={}, zones=[])
        self.expected["azurerm_role_definition.expiry"]["permissions"][0].update(not_actions=[], data_actions=[], not_data_actions=[])
        self.expected["azurerm_subnet.window"].update(network_security_group_id=nsg_id, service_endpoint_policy_ids=[])
        self.expected["azurerm_virtual_network.window"]["subnet"] = [{"id": subnet["id"], "name": "gpu",
            "address_prefixes": ["10.239.0.0/24"], "default_outbound_access_enabled": True, "delegation": [],
            "private_endpoint_network_policies": "Disabled", "private_link_service_network_policies_enabled": True,
            "route_table_id": "", "service_endpoint": [], "service_endpoint_policy_ids": [], "security_group": nsg_id}]
        plan_outputs = {name: dict(row, sensitive=False) for name, row in self.state_data["outputs"].items()}
        resources = [{"address": address, "mode": "managed", "type": address.split(".")[0],
            "name": address.split(".")[1], "provider_name": "registry.terraform.io/hashicorp/azurerm", "values": value}
            for address, value in self.expected.items()]
        variables = dict(self.old_inputs, confidential_image_id=self.original["azurerm_linux_virtual_machine.gpu"]["source_image_id"], model_container_scope="")
        self.plan = {"terraform_version": "1.12.2", "complete": True, "errored": False,
            "variables": {key: {"value": value} for key, value in variables.items()},
            "planned_values": {"root_module": {}, "outputs": plan_outputs},
            "prior_state": {"values": {"root_module": {"resources": resources}, "outputs": plan_outputs}},
            "resource_drift": [{"address": address, "change": {"actions": ["update"], "before": self.original[address],
                "after": self.expected[address], "after_unknown": {}}} for address in resume.REFRESH_ADDRESSES],
            "output_changes": {name: {"actions": ["no-op"], "before": row["value"], "after": row["value"], "after_unknown": False}
                for name, row in self.state_data["outputs"].items()}}
        self.saved_check.return_value = self.plan

    def validate(self, plan=None):
        return resume.validate_refresh_plan(plan or self.plan, self.state_data, self.old_inputs, self.nic)

    def make_plan(self):
        calls = []
        def tf(*args, **kwargs):
            calls.append(args)
            if args[0] == "plan":
                (self.refresh / "plan.tfplan").write_bytes(b"CPU_REFRESH_ONLY_BINARY_FIXTURE")
        args = argparse.Namespace(retained_window=self.old.name, refresh_id=self.refresh.name)
        with patch.object(resume, "require_deallocated", return_value=self.vm), \
             patch.object(resume.window, "az_json", return_value=self.nic), \
             patch.object(resume.window, "tf", side_effect=tf), patch("builtins.print"):
            resume.refresh_plan(args)
        return calls

    def test_actual_refresh_shape_preserves_resources_with_explicit_normalizations(self):
        self.assertEqual(self.validate(), self.expected)
        plan = copy.deepcopy(self.plan)
        plan["resource_changes"] = [{"address": address, "change": {"actions": ["no-op"], "before": value,
            "after": value, "after_unknown": {}}} for address, value in self.expected.items()]
        self.assertEqual(self.validate(plan), self.expected)

    def test_extra_missing_duplicate_drift_and_resource_mutations_rejected(self):
        mutations = [lambda p: p["resource_drift"].pop(),
            lambda p: p["resource_drift"].append(copy.deepcopy(p["resource_drift"][0])),
            lambda p: p["resource_drift"][0].update(previous_address="moved"),
            lambda p: p["resource_drift"][0]["change"].update(after_unknown={"id": True}),
            lambda p: p.update(resource_changes=[{"address": next(iter(resume.ADDRESSES)), "change": {"actions": ["create"]}}]),
            lambda p: p["prior_state"]["values"]["root_module"]["resources"].append(copy.deepcopy(p["prior_state"]["values"]["root_module"]["resources"][0])),
            lambda p: p["planned_values"].update(root_module={"resources": p["prior_state"]["values"]["root_module"]["resources"]})]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                plan = copy.deepcopy(self.plan); mutation(plan)
                with self.assertRaises(ValueError): self.validate(plan)

    def test_silent_vm_security_and_unapproved_drift_fields_rejected(self):
        for address, key, value in [("azurerm_linux_virtual_machine.gpu", "secure_boot_enabled", False),
                ("azurerm_linux_virtual_machine.gpu", "termination_notification", [{"enabled": True}]),
                ("azurerm_logic_app_workflow.expiry", "tags", {"expires_at": "later"}),
                ("azurerm_role_definition.expiry", "permissions", [{"actions": ["*"]}])]:
            with self.subTest(address=address, key=key):
                plan = copy.deepcopy(self.plan)
                row = next(row for row in plan["prior_state"]["values"]["root_module"]["resources"] if row["address"] == address)
                row["values"][key] = value
                with self.assertRaises(ValueError): self.validate(plan)

    def test_original_relationships_mac_inputs_and_output_changes_rejected(self):
        for mutation in (lambda p: p["variables"]["confidential_image_id"].update(value="/changed/image"),
                lambda p: p["variables"]["model_container_scope"].update(value="/other/scope"),
                lambda p: p["output_changes"]["expiry"].update(after="later"),
                lambda p: p["planned_values"]["outputs"].pop("vm_id")):
            plan = copy.deepcopy(self.plan); mutation(plan)
            with self.assertRaises(ValueError): self.validate(plan)
        for field, value in (("macAddress", "invalid"), ("id", "/another/nic"),
                ("virtualMachine", {"id": "/another/vm"})):
            with self.assertRaises(ValueError):
                resume.validate_refresh_plan(self.plan, self.state_data, self.old_inputs, dict(self.nic, **{field: value}))

    def test_refresh_plan_snapshots_exact_bytes_and_uses_only_read_only_commands(self):
        before = {p.name: p.read_bytes() for p in self.old.iterdir() if p.is_file()}
        with patch.object(resume.window, "command") as mutation:
            calls = self.make_plan()
            mutation.assert_not_called()
        self.assertEqual([call[0] for call in calls], ["init", "plan"])
        self.assertIn("-refresh-only", calls[1])
        self.assertEqual((self.refresh / "terraform.tfstate-before").read_bytes(), before["terraform.tfstate"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.old.iterdir() if p.is_file()})
        self.assertFalse(resume.load(self.refresh / "summary.json")["vm_start_requested"])

    def test_apply_writes_only_validated_saved_state_and_keeps_vm_deallocated(self):
        self.make_plan()
        calls = []
        def tf(*args, **kwargs):
            calls.append(args)
            if args[0] == "apply":
                state = copy.deepcopy(self.state_data)
                state["serial"] += 1
                for row in state["resources"]:
                    row["instances"][0]["attributes"] = self.expected[row["type"] + "." + row["name"]]
                self.json(self.old / "terraform.tfstate", state)
        digest = resume.window.sha(self.refresh / "plan.tfplan")
        with patch.object(resume, "require_deallocated", return_value=self.vm) as off, \
             patch.object(resume.window, "az_json", return_value=self.nic), \
             patch.object(resume.window, "tf", side_effect=tf), \
             patch.object(resume.window, "command") as mutation:
            resume.refresh_apply(self.refresh, digest)
            mutation.assert_not_called()
        self.assertEqual(off.call_count, 2)
        self.assertEqual([call[0] for call in calls], ["init", "apply"])
        self.assertEqual(calls[1][2], str(self.refresh / "plan.tfplan"))
        receipt = resume.load(self.refresh / "apply-receipt.json")
        self.assertEqual(receipt["state"], "VERIFIED_REFRESH_ONLY_STATE_RECONCILIATION")
        self.assertTrue(receipt["deallocation_verified"])
        self.assertFalse(receipt["vm_start_requested"])

    def test_changed_hash_and_backend_rejected_before_cloud_or_apply(self):
        self.make_plan()
        digest = resume.window.sha(self.refresh / "plan.tfplan")
        for path in (self.refresh / "plan.tfplan", self.old / "terraform.tfstate", self.refresh / "nic-readback.json"):
            before = path.read_bytes(); path.write_bytes(before + b" ")
            with patch.object(resume.window, "az_json") as cloud, patch.object(resume.window, "tf") as tf:
                with self.assertRaises(ValueError): resume.refresh_apply(self.refresh, digest)
                cloud.assert_not_called(); tf.assert_not_called()
            path.write_bytes(before)

    def test_apply_failure_preserves_originals_without_starting_or_deleting(self):
        self.make_plan()
        before = (self.old / "terraform.tfstate").read_bytes()
        with patch.object(resume, "require_deallocated", return_value=self.vm), \
             patch.object(resume.window, "az_json", return_value=self.nic), \
             patch.object(resume.window, "tf", side_effect=RuntimeError("CPU state-only apply failure fixture")), \
             patch.object(resume.window, "command") as mutation:
            with self.assertRaises(RuntimeError): resume.refresh_apply(self.refresh, resume.window.sha(self.refresh / "plan.tfplan"))
            mutation.assert_not_called()
        self.assertEqual((self.old / "terraform.tfstate").read_bytes(), before)
        receipt = resume.load(self.refresh / "apply-receipt.json")
        self.assertEqual(receipt["state"], "FAILED_REFRESH_STATE_RECONCILIATION")
        self.assertTrue(receipt["temporary_resources_retained_for_user_decision"])

    def test_post_apply_serial_outputs_and_resource_mismatches_fail_closed(self):
        for index, mutation in enumerate((lambda s: s.update(serial=14),
                lambda s: s["outputs"]["expiry"].update(value="unreviewed-expiry"),
                lambda s: s["resources"][0]["instances"][0]["attributes"].update(id="/unreviewed/resource"))):
            with self.subTest(index=index):
                self.json(self.old / "terraform.tfstate", self.state_data)
                self.make_plan()
                def tf(*args, **kwargs):
                    if args[0] == "apply":
                        state = copy.deepcopy(self.state_data)
                        state["serial"] += 1
                        for row in state["resources"]:
                            row["instances"][0]["attributes"] = copy.deepcopy(self.expected[row["type"] + "." + row["name"]])
                        mutation(state)
                        self.json(self.old / "terraform.tfstate", state)
                with patch.object(resume, "require_deallocated", return_value=self.vm), \
                     patch.object(resume.window, "az_json", return_value=self.nic), \
                     patch.object(resume.window, "tf", side_effect=tf), patch.object(resume.window, "command") as cloud:
                    with self.assertRaisesRegex(ValueError, "Actual refreshed backend differs"):
                        resume.refresh_apply(self.refresh, resume.window.sha(self.refresh / "plan.tfplan"))
                    cloud.assert_not_called()
                receipt = resume.load(self.refresh / "apply-receipt.json")
                self.assertFalse(receipt["deallocation_verified"])
                self.assertFalse(receipt["vm_start_requested"])
                self.assertTrue((self.refresh / "terraform.tfstate-before").exists())
                self.assertTrue((self.refresh / "terraform.tfstate-after").exists())
                self.refresh.rename(self.state / ("failed-refresh-" + str(index)))


if __name__ == "__main__":
    unittest.main()
