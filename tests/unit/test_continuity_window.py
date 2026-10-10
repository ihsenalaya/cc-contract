import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("continuity_window", ROOT / "scripts/continuity-window.py")
window = importlib.util.module_from_spec(spec)
spec.loader.exec_module(window)


def guard():
    auth = {"type": "ManagedServiceIdentity", "audience": "https://management.azure.com/"}
    uri = "https://management.azure.com" + window.VM
    get = dict(type="Http", inputs=dict(method="GET", uri=uri + "/instanceView?api-version=2024-03-01", authentication=auth))
    release = dict(type="Http", inputs=dict(method="POST", uri=uri + "/deallocate?api-version=2024-03-01", authentication=auth))
    condition = dict(type="If", runAfter={"GetState": ["Succeeded"]},
                     expression={"not": {"contains": ["@string(body('GetState'))", "PowerState/deallocated"]}},
                     actions={"Deallocate": release})
    definition = dict(triggers={"ExpiryTick": {"type": "Recurrence", "recurrence": {"frequency": "Minute", "interval": 1}}},
                      actions={"ExpiryGuard": dict(type="If", expression={"greaterOrEquals": ["@ticks(utcNow())", "old"]},
                                                    actions={"GetState": get, "IfAllocated": condition})})
    return dict(id="existing-guard", properties={"state": "Enabled", "definition": definition})


def plan():
    return dict(protocol="state-continuity-pilot-v0.1", vm_id=window.VM, vm_uuid=window.UUID, disk_uuid=window.DISK_UUID,
                image="ghcr.io/ihsenalaya/cc-contract-continuity@sha256:" + "a" * 64,
                runs=50, gpu_parallelism=1, creates=0, destroys=0, max_minutes=30, budget_usd=5,
                controller_sha256=window.sha(ROOT / "scripts/continuity-window.py"),
                host_script_sha256=window.sha(ROOT / "scripts/run-continuity-host.sh"), guard_id="existing-guard",
                guard_definition_sha256=hashlib.sha256(json.dumps(guard()["properties"]["definition"], sort_keys=True).encode()).hexdigest())


def approval(plan_hash):
    return dict(approved_by="user", approved=True, plan_sha256=plan_hash, protocol="state-continuity-pilot-v0.1",
                max_minutes=30, budget_usd=5, reuse_completed_authorization=False,
                approved_utc=datetime.now(timezone.utc).isoformat())


def archive(tamper=False):
    content = b"original observation"
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        files = {"record.json": content, "hashes.json": json.dumps({"record.json": "wrong" if tamper else hashlib.sha256(content).hexdigest()}).encode()}
        for name, raw in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
    return output.getvalue()


class WindowTests(unittest.TestCase):
    def test_approval_rejects_stale_missing_or_larger_scope(self):
        good = approval("hash")
        now = datetime.now(timezone.utc)
        window.validate_approval(plan(), good, "hash", now)
        for change in ({"approved": False}, {"budget_usd": 15}, {"max_minutes": 90},
                       {"plan_sha256": "other"}, {"reuse_completed_authorization": True},
                       {"approved_utc": "2020-01-01T00:00:00+00:00"}):
            with self.assertRaises(ValueError):
                window.validate_approval(plan(), dict(good, **change), "hash", now)
        for change in ({"creates": 1}, {"destroys": 1}, {"runs": 140}, {"gpu_parallelism": 2}, {"vm_uuid": "other"}):
            with self.assertRaises(ValueError):
                window.validate_approval(dict(plan(), **change), good, "hash", now)

    def test_guard_rejects_wrong_target_disabled_or_condition(self):
        window.validate_guard(guard())
        for change in ("disabled", "other-vm", "wrong-condition"):
            candidate = guard()
            if change == "disabled":
                candidate["properties"]["state"] = "Disabled"
            else:
                conditional = candidate["properties"]["definition"]["actions"]["ExpiryGuard"]["actions"]["IfAllocated"]
                if change == "other-vm":
                    conditional["actions"]["Deallocate"]["inputs"]["uri"] = "different"
                else:
                    conditional["expression"] = {"equals": [1, 2]}
            with self.assertRaises(ValueError):
                window.validate_guard(candidate)

    def test_archive_hashes_checked_without_extraction(self):
        self.assertTrue(window.verify_archive(archive())["hashes_verified"])
        with self.assertRaises(ValueError):
            window.verify_archive(archive(tamper=True))

    def exercise(self, failure):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            retained = root / "work-sample-1009b"
            retained.mkdir()
            (retained / "outputs.json").write_text(json.dumps({"ssh_address": {"value": "192.0.2.1"}}))
            folder = root / "window"
            folder.mkdir()
            window.write(folder / "plan.json", plan())
            window.write(folder / "approval.json", approval(window.sha(folder / "plan.json")))
            args = SimpleNamespace(directory=folder, approval=folder / "approval.json")
            calls = []
            def azure(*arguments):
                calls.append(arguments)
                if arguments[:2] == ("resource", "show"):
                    current = guard()
                    current["properties"]["definition"] = json.loads((folder / "guard-update.json").read_text())["properties"]["definition"]
                    return current
                if arguments[:2] == ("vm", "get-instance-view"):
                    return {"instanceView": {"statuses": [{"code": "PowerState/deallocated"}]}}
                if arguments[:2] == ("vm", "start") and failure == "start":
                    raise RuntimeError("start failed after request")
            def run(arguments, **kwargs):
                if arguments[0] == "gh":
                    return subprocess.CompletedProcess(arguments, 0, b"", b"Token: testtoken")
                if arguments[-1].startswith("bash -s"):
                    if failure == "host":
                        raise subprocess.TimeoutExpired(arguments, 810)
                    if failure == "interrupt":
                        raise KeyboardInterrupt()
                if arguments[-1].startswith("tar -czf"):
                    return subprocess.CompletedProcess(arguments, 0, archive(tamper=failure == "collection"), b"")
                return subprocess.CompletedProcess(arguments, 0, b"", b"")
            with patch.object(window, "STATE", root), patch.object(window, "inventory", return_value={"guard": guard()}), \
                    patch.object(window, "az", side_effect=azure), patch.object(window.subprocess, "run", side_effect=run):
                if failure:
                    with self.assertRaises((RuntimeError, ValueError, subprocess.TimeoutExpired, KeyboardInterrupt)):
                        window.execute(args)
                else:
                    window.execute(args)
                self.assertEqual(sum(c[:2] == ("vm", "start") for c in calls), 1)
                self.assertEqual(sum(c[:2] == ("vm", "deallocate") for c in calls), 1)
                self.assertTrue((folder / "release.json").exists())
                with self.assertRaises(FileExistsError):
                    window.execute(args)

    def test_success_deallocates(self):
        self.exercise(None)

    def test_failed_start_deallocates(self):
        self.exercise("start")

    def test_timeout_deallocates(self):
        self.exercise("host")

    def test_interrupt_deallocates(self):
        self.exercise("interrupt")

    def test_failed_collection_deallocates(self):
        self.exercise("collection")


if __name__ == "__main__":
    unittest.main()
