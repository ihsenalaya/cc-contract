"""CPU-only receipt fixtures for cumulative zero-work H100 retry allowance."""
import argparse
import copy
from datetime import timedelta
import hashlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("budget_resume_fixtures", ROOT / "tests/unit/test_resume_campaign.py")
fixtures = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixtures)
resume = fixtures.resume


class PriorAttemptBudgetTests(unittest.TestCase):
    json = staticmethod(fixtures.ResumeCampaignTests.json)
    tags = staticmethod(fixtures.ResumeCampaignTests.tags)

    def setUp(self):
        fixtures.ResumeCampaignTests.setUp(self)
        self.bundle.update(campaign_id=self.new.name, planned_jobs=140, selected_cases_per_job=100,
                           gpu_jobs_parallel=False, images={})
        self.prior = self.state / "preserved-first-ssh-failure"; self.prior.mkdir()
        self.sources = {"azure-resume-campaign.py": resume.HERE.read_bytes(),
            "azure-window.py": resume.HERE.with_name("azure-window.py").read_bytes(),
            "qualify-host.sh": (self.root / "scripts/qualify-host.sh").read_bytes()}
        qualification = self.base / "original-local-qualification.json"
        self.json(qualification, {"git_source_commit": "CPU_ORIGINAL_SOURCE_FIXTURE",
            "resume_controller_sha256": hashlib.sha256(self.sources["azure-resume-campaign.py"]).hexdigest(),
            "cloud_controller_sha256": hashlib.sha256(self.sources["azure-window.py"]).hexdigest(),
            "host_script_sha256": hashlib.sha256(self.sources["qualify-host.sh"]).hexdigest()})
        self.bundle.update(local_qualification_path=str(qualification), local_qualification_sha256=resume.window.sha(qualification))
        self.json(self.prior / "workload-bundle.json", self.bundle)
        (self.prior / "plan.tfplan").write_bytes(b"CPU_ORIGINAL_PRIOR_BINARY_PLAN")
        summary = dict(self.summary, planned_at_utc=(self.now - timedelta(minutes=30)).isoformat(),
            plan_sha256=resume.window.sha(self.prior / "plan.tfplan"),
            workload_bundle_sha256=resume.window.sha(self.prior / "workload-bundle.json"))
        self.json(self.prior / "summary.json", summary)
        self.json(self.prior / "approved-workload-plan.json", summary)
        self.json(self.prior / "user-approval.json", dict(self.approval, plan_sha256=summary["plan_sha256"],
            approved_at_utc=(self.now - timedelta(minutes=29)).isoformat()))
        begin = self.now - timedelta(minutes=10)
        end = begin + timedelta(seconds=179.295374)
        self.json(self.prior / "run-start.json", {"timestamp_utc": (begin-timedelta(seconds=30)).isoformat(),
            "retained_vm_uuid": self.uuid, "plan_sha256": summary["plan_sha256"]})
        self.json(self.prior / "start-request.json", {"timestamp_utc": begin.isoformat()})
        self.json(self.prior / "release.json", {"timestamp_utc": end.isoformat(),
            "power_state": "PowerState/deallocated", "retained_os_disk": True})
        self.json(self.prior / "run-exit.json", {"timestamp_utc": (end+timedelta(seconds=3)).isoformat(),
            "error_type": "CalledProcessError", "release_error_type": None, "resources_destroyed_automatically": False,
            "deallocation_verified": True, "elapsed_seconds": 213})
        self.json(self.prior / "vm-identity.json", [{"type": "azurerm_linux_virtual_machine", "name": "gpu",
            "instances": [{"attributes": self.original["azurerm_linux_virtual_machine.gpu"]}]}])
        self.json(self.prior / "renewed-guard-readback.json", {"vm_uuid": self.uuid, "power_state": "PowerState/deallocated"})
        (self.prior / "run-controller.stderr").write_text("CPU fixture: Connection timed out\n")
        self.json(self.prior / "run-phases.jsonl", {"phase": "qualify_collect_release", "state": "FAILED", "error_type": "CalledProcessError"})
        self.git = patch.object(resume.subprocess, "check_output", side_effect=lambda args, **kwargs:self.sources[args[-1].split('/')[-1]]).start()

    def allowance(self, paths=None):
        return resume.prior_attempt_budget(paths or [self.prior], self.new.name, self.old.name,
            self.original["azurerm_linux_virtual_machine.gpu"], self.bundle, 15)

    def test_original_three_minute_failure_leaves_only_87_minutes_same_total_budget(self):
        receipt = self.allowance()
        self.assertEqual(receipt["prior_conservatively_charged_vm_seconds"], 179.295374)
        self.assertEqual(receipt["new_plan_maximum_minutes"], 87)
        self.assertEqual(receipt["budget_forecast_total_usd"], 15)
        self.assertLessEqual(179.295374 + 87 * 60, 90 * 60)
        self.assertEqual(receipt["attempts"][0]["gpu_jobs_started"], 0)

    def test_duplicates_qualified_attempts_wrong_uuid_and_failed_stop_rejected(self):
        with self.assertRaises(ValueError): self.allowance([self.prior, self.prior])
        for name in ("qualification-session.log", "qualification-session.json", "qualification-exit.json", "collection.json"):
            path = self.prior / name; path.write_text("CPU marker")
            with self.assertRaises(ValueError): self.allowance()
            path.unlink()
        for name, key, value in (("release.json", "power_state", "PowerState/running"),
                ("run-exit.json", "deallocation_verified", False),
                ("renewed-guard-readback.json", "vm_uuid", "another-VM")):
            path = self.prior / name; before = path.read_bytes(); data = resume.load(path);data[key] = value;self.json(path, data)
            with self.assertRaises(ValueError):self.allowance()
            path.write_bytes(before)

    def test_smaller_original_authorization_or_changed_scientific_quota_rejected(self):
        for field, value in (("max_window_minutes", 75), ("budget_forecast_usd", 20)):
            paths = [self.prior / "summary.json", self.prior / "approved-workload-plan.json"]
            originals = [path.read_bytes() for path in paths]
            for path in paths:
                data = resume.load(path);data[field] = value;self.json(path, data)
            with self.assertRaises(ValueError):self.allowance()
            for path, original in zip(paths, originals):path.write_bytes(original)
        with self.assertRaises(ValueError):
            resume.prior_attempt_budget([self.prior], self.new.name, self.old.name,
                self.original["azurerm_linux_virtual_machine.gpu"], dict(self.bundle, selected_cases_per_job=1000), 15)

    def test_retry_plan_carries_original_hashes_and_changed_receipt_blocks_run_before_cloud(self):
        self.new.rename(self.state / "unused-initial-fixture")
        bundle_path = self.base / "current-bundle.json";self.json(bundle_path, self.bundle)
        self.bundle_check.return_value = self.bundle
        args = argparse.Namespace(campaign=self.new.name, retained_window=self.old.name,
            max_window_minutes=90, budget_forecast_usd=15, workload_bundle=bundle_path,
            ssh_source_cidr=None, expires_at_utc=None, prior_attempt=[self.prior])
        def tf(*values, **kwargs):
            if values[0] == "plan":
                (self.new / "plan.tfplan").write_bytes(b"CPU_CUMULATIVE_RETRY_PLAN")
                inputs = resume.load(self.new / "inputs.json")
                self.plan["variables"] = {k:{"value":v} for k,v in inputs.items()}
                for row in self.plan["resource_changes"]:
                    if row["address"] in resume.TAGGED:row["change"]["after"]["tags"] = self.tags(inputs)
                    if row["address"] == "azurerm_logic_app_action_custom.expiry":
                        body = resume.json.loads(row["change"]["after"]["body"])
                        body["expression"]["greaterOrEquals"][1] = "@ticks('" + inputs["expires_at_utc"] + "')"
                        row["change"]["after"]["body"] = resume.json.dumps(body)
        with patch.object(resume, "require_deallocated", return_value=self.vm), patch.object(resume.window, "tf", side_effect=tf), patch("builtins.print"):
            resume.plan_campaign(args)
        summary = resume.load(self.new / "summary.json")
        self.assertEqual(summary["max_window_minutes"], 87)
        self.assertEqual(summary["expires_at_utc"], "2026-10-10T02:27:00Z")
        self.json(self.new / "user-approval.json", dict(self.approval, plan_sha256=summary["plan_sha256"],
            approved_at_utc=None, binding_source="EXISTING_EXPLICIT_USER_INSTRUCTION",
            plan_bound_at_utc=self.now.isoformat(), user_has_not_seen_plan_sha256=True, max_window_minutes=87))
        resume.verify_run(self.new, summary["plan_sha256"])
        receipt = self.prior / "release.json";receipt.write_bytes(receipt.read_bytes()+b" ")
        with patch.object(resume.window, "az_json") as cloud:
            with self.assertRaisesRegex(ValueError, "receipt hashes changed"):
                resume.verify_run(self.new, summary["plan_sha256"])
            cloud.assert_not_called()


if __name__ == "__main__":
    unittest.main()
