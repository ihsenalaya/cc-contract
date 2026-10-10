"""CPU tests of bounded SSH boot readiness and retained-backend retry inputs."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("startup_resume_fixtures", ROOT / "tests/unit/test_resume_campaign.py")
fixtures = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixtures)
resume = fixtures.resume


class StartupReadinessTests(unittest.TestCase):
    json = staticmethod(fixtures.ResumeCampaignTests.json)
    tags = staticmethod(fixtures.ResumeCampaignTests.tags)

    def setUp(self):
        fixtures.ResumeCampaignTests.setUp(self)
        self.running = {"instanceView": {"statuses": [{"code": "PowerState/running"}]}}

    def test_running_but_refused_ssh_retries_within_same_startup_deadline(self):
        refused = subprocess.CompletedProcess([], 255, stderr=b"connect to host: Connection refused")
        ready = subprocess.CompletedProcess([], 0, stderr=b"")
        with patch.object(resume.window, "command"), patch.object(resume.time, "monotonic", return_value=0), \
             patch.object(resume.time, "sleep"), \
             patch.object(resume, "bounded_az_json", side_effect=[self.running, self.vm, self.running, self.vm, self.vm, self.running]) as azure, \
             patch.object(resume.subprocess, "run", side_effect=[refused, ready]) as ssh:
            resume.start_and_wait(self.vm_id, self.uuid, self.new)
        self.assertEqual({call.args[1] for call in azure.call_args_list}, {resume.START_TIMEOUT_SECONDS})
        self.assertEqual(ssh.call_count, 2)
        self.assertTrue(all(call.args[0][-1] == "true" and call.kwargs["timeout"] == 15 for call in ssh.call_args_list))
        rows = [json.loads(line) for line in (self.new / "ssh-readiness.jsonl").read_text().splitlines()]
        self.assertEqual([row["classification"] for row in rows], ["CONNECTION_REFUSED", "READY"])
        self.assertTrue(all(row["gpu_command_executed"] is False for row in rows))
        self.assertTrue(resume.load(self.new / "startup-ready.json")["ssh_true_succeeded"])

    def test_late_running_state_does_not_reset_ssh_budget(self):
        clock = [0]
        def azure(args, deadline):
            clock[0] = resume.START_TIMEOUT_SECONDS - 1
            return self.running if args[1] == "get-instance-view" else self.vm
        def failed_ssh(*args, **kwargs):
            self.assertEqual(kwargs["timeout"], 1)
            clock[0] = resume.START_TIMEOUT_SECONDS + 1
            raise subprocess.TimeoutExpired("ssh", kwargs["timeout"])
        with patch.object(resume.window, "command"), patch.object(resume.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(resume, "bounded_az_json", side_effect=azure), \
             patch.object(resume.subprocess, "run", side_effect=failed_ssh):
            with self.assertRaisesRegex(TimeoutError, "15 minutes"):
                resume.start_and_wait(self.vm_id, self.uuid, self.new)
        self.assertFalse((self.new / "startup-ready.json").exists())
        self.assertEqual(json.loads((self.new / "ssh-readiness.jsonl").read_text())["classification"], "PROBE_DEADLINE")

    def test_auth_host_key_and_cancellation_are_fatal_and_logged_without_stderr(self):
        for index, message in enumerate((b"Permission denied SENSITIVE_FIXTURE", b"REMOTE HOST IDENTIFICATION HAS CHANGED SENSITIVE_FIXTURE")):
            directory = self.state / ("ssh-failure-" + str(index)); directory.mkdir()
            with patch.object(resume.subprocess, "run", return_value=subprocess.CompletedProcess([], 255, stderr=message)):
                with self.assertRaises(ValueError): resume.ssh_probe(directory, self.outputs, resume.time.monotonic() + 30)
            text = (directory / "ssh-readiness.jsonl").read_text()
            self.assertNotIn("SENSITIVE_FIXTURE", text)
        directory = self.state / "ssh-cancelled"; directory.mkdir()
        with patch.object(resume.subprocess, "run", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): resume.ssh_probe(directory, self.outputs, resume.time.monotonic() + 30)
        self.assertEqual(json.loads((directory / "ssh-readiness.jsonl").read_text())["classification"], "KeyboardInterrupt")

    def test_successful_ssh_cannot_promote_changed_vm_identity(self):
        with patch.object(resume.window, "command"), patch.object(resume, "ssh_probe", return_value=True), \
             patch.object(resume, "bounded_az_json", side_effect=[self.running, self.vm, {"vmId": "changed"}, self.running]):
            with self.assertRaisesRegex(ValueError, "UUID changed during SSH readiness"):
                resume.start_and_wait(self.vm_id, self.uuid, self.new)
        self.assertFalse((self.new / "startup-ready.json").exists())

    def test_changed_campaign_ssh_output_rejected_before_cloud_access(self):
        outputs = copy.deepcopy(self.outputs)
        outputs["ssh_address"]["value"] = "203.0.113.4"
        self.json(self.new / "outputs.json", outputs)
        with patch.object(resume.window, "az_json") as azure:
            with self.assertRaisesRegex(ValueError, "Campaign SSH outputs differ"):
                resume.verify_run(self.new, self.summary["plan_sha256"])
            azure.assert_not_called()

    def current_backend(self):
        state = copy.deepcopy(self.state_data)
        resources = resume.state_resources(state)
        for address in resume.TAGGED:
            resources[address]["tags"] = self.tags(self.inputs)
        resources["azurerm_network_security_group.window"]["security_rule"][0]["source_address_prefix"] = "198.51.100.2/32"
        guard = json.loads(resources["azurerm_logic_app_action_custom.expiry"]["body"])
        guard["expression"]["greaterOrEquals"][1] = "@ticks('" + self.inputs["expires_at_utc"] + "')"
        resources["azurerm_logic_app_action_custom.expiry"]["body"] = json.dumps(guard)
        state["outputs"]["expiry"]["value"] = self.inputs["expires_at_utc"]
        return state

    def test_current_backend_inputs_reconcile_previous_renewal_without_modifying_originals(self):
        state = self.current_backend()
        current, outputs = resume.operational_inputs(self.old_inputs, state)
        self.assertEqual(current, dict(self.inputs, ssh_source_cidr="198.51.100.2/32"))
        self.assertEqual(outputs["expiry"]["value"], self.inputs["expires_at_utc"])
        self.assertEqual(resume.load(self.old / "inputs.json"), self.old_inputs)
        self.assertEqual(resume.load(self.old / "outputs.json"), self.outputs)
        for mutation in (lambda s: s["outputs"]["expiry"].update(value="2026-10-10T03:00:00Z"),
                lambda s: resume.state_resources(s)["azurerm_network_interface.window"]["tags"].update(expires_at="2026-10-10T03:00:00Z"),
                lambda s: s["outputs"]["ssh_address"].update(value="203.0.113.4")):
            changed = copy.deepcopy(state); mutation(changed)
            with self.assertRaises(ValueError): resume.operational_inputs(self.old_inputs, changed)

    def test_retry_plan_keeps_current_deadline_and_validates_current_guard(self):
        self.new.rename(self.state / "preserved-first-failed-attempt")
        state = self.current_backend()
        self.json(self.old / "terraform.tfstate", state)
        before = {p.name: p.read_bytes() for p in self.old.iterdir() if p.is_file()}
        bundle = self.base / "retry-bundle.json"; self.json(bundle, self.bundle)
        args = argparse.Namespace(campaign=self.new.name, retained_window=self.old.name,
            max_window_minutes=90, budget_forecast_usd=15, workload_bundle=bundle, ssh_source_cidr=None, expires_at_utc=None)
        def tf(*values, **kwargs):
            if values[0] == "plan":
                (self.new / "plan.tfplan").write_bytes(b"CPU_RETRY_PLAN")
                inputs = resume.load(self.new / "inputs.json")
                self.plan = {"variables": {k: {"value": v} for k, v in inputs.items()}, "resource_changes": []}
                for address, old in resume.state_resources(state).items():
                    after = copy.deepcopy(old)
                    if address in resume.TAGGED: after["tags"] = self.tags(inputs)
                    self.plan["resource_changes"].append({"address": address, "change": {
                        "actions": ["no-op"] if old == after else ["update"], "before": old, "after": after, "after_unknown": {}}})
                self.saved_check.return_value = self.plan
        with patch.object(resume, "require_deallocated", return_value=self.vm), patch.object(resume.window, "tf", side_effect=tf), patch("builtins.print"):
            resume.plan_campaign(args)
        summary = resume.load(self.new / "summary.json")
        self.assertEqual(summary["expires_at_utc"], self.inputs["expires_at_utc"])
        self.assertTrue(summary["retry_preserves_absolute_deadline"])
        self.assertEqual(summary["old_inputs"]["expires_at_utc"], self.inputs["expires_at_utc"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.old.iterdir() if p.is_file()})
        self.new.rename(self.state / "preserved-retry-plan")
        args.expires_at_utc = "2026-10-10T02:30:00Z"
        with patch.object(resume, "require_deallocated", return_value=self.vm):
            with self.assertRaisesRegex(ValueError, "may not extend"):
                resume.plan_campaign(args)


if __name__ == "__main__":
    unittest.main()
