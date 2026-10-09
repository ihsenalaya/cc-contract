"""Control-flow tests with explicit CPU fixtures; no hardware evidence."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("window", ROOT / "scripts/azure-window.py")
window = importlib.util.module_from_spec(spec)
spec.loader.exec_module(window)


class InfrastructureTests(unittest.TestCase):
    def test_windows_cli_encoding_is_preserved(self):
        raw = '{"name":"abonnement expérimental"}'.encode("cp1252")
        with patch.object(window.subprocess, "check_output", return_value=raw):
            self.assertEqual(window.az_json("account", "show")["name"], "abonnement expérimental")

    def test_deallocate_no_json_response_and_state_is_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = {"vm_id": {"value": "/subscriptions/fixture/resourceGroups/cc-contract-fixture/providers/Microsoft.Compute/virtualMachines/cc-contract-fixture"}}
            state = {"instanceView": {"statuses": [{"code": "PowerState/deallocated"}]}}
            with patch.object(window, "ensure_window", return_value=({}, outputs)), patch.object(window, "command") as cmd, patch.object(window, "az_json", return_value=state), patch("sys.stdout", new_callable=io.StringIO):
                window.release(Path(tmp))
                self.assertEqual(cmd.call_args[0][0][1], "vm")
                self.assertEqual(cmd.call_args[0][0][2], "deallocate")
                self.assertEqual(json.loads((Path(tmp) / "release.json").read_text())["power_state"], "PowerState/deallocated")

    def test_export_failure_still_releases_and_does_not_authorize_destroy(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with patch.object(window, "ensure_window", return_value=({}, {})), patch.object(window, "ssh_args", return_value=["fixture-ssh"]), patch.object(window.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "fixture-ssh")), patch.object(window, "release") as release:
                with self.assertRaises(subprocess.CalledProcessError):
                    window.collect_and_release(directory)
                release.assert_called_once_with(directory)
                self.assertFalse((directory / "collection.json").exists())

    def test_finalized_archive_is_verified_and_never_overwritten(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            archive = directory / "guest-evidence-fixture.tar.gz"
            archive.write_bytes(b"CPU fixture finalized archive")
            before = archive.read_bytes()
            (directory / "collection.json").write_text(json.dumps({"archive_file": archive.name, "archive_sha256": hashlib.sha256(before).hexdigest()}))
            with patch.object(window, "ensure_window", return_value=({}, {})), patch.object(window, "release") as release:
                window.collect_and_release(directory)
                release.assert_called_once_with(directory)
            self.assertEqual(archive.read_bytes(), before)

    def test_qualification_nonzero_is_propagated_after_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.config/gh').mkdir(parents=True)
            (root / '.config/gh/hosts.yml').write_text('  oauth_token: MOCK_FIXTURE_ONLY\n')
            (root / '.local/cuda').mkdir(parents=True)
            (root / '.local/cuda/remote-digest').write_text('ghcr.io/ihsenalaya/cc-contract-cuda@sha256:' + 'a' * 64)
            (root / 'scripts').mkdir()
            (root / 'scripts/qualify-host.sh').write_text('echo MOCK_FIXTURE_ONLY\n')
            state = root / 'state'
            state.mkdir()
            completed = subprocess.CompletedProcess('MOCK_FIXTURE_ONLY', 1)
            with patch.object(window, 'ROOT', root), patch.object(window, 'STATE', state), patch.object(window.Path, 'home', return_value=root), patch.object(window, 'ensure_window', return_value=({}, {})), patch.object(window, 'ssh_args', return_value=['MOCK_FIXTURE_SSH']), patch.object(window, 'command'), patch.object(window.subprocess, 'run', return_value=completed), patch.object(window, 'collect_and_release') as cleanup, patch('sys.argv', ['window', 'qualify', '--window', 'fixture']):
                self.assertEqual(window.main(), 1)
                cleanup.assert_called_once_with(state / 'fixture')
            self.assertEqual(json.loads((state / 'fixture/qualification-exit.json').read_text())['returncode'], 1)

    def test_run_still_destroys_verified_window_when_qualification_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            directory = state / 'fixture'
            directory.mkdir()
            plan = directory / 'plan.tfplan'
            plan.write_bytes(b'MOCK_PLAN_ONLY')
            (directory / 'collection.json').write_text('{"scope":"MOCK_COLLECTION_ONLY"}')
            calls = []
            def child(args):
                calls.append(args[2])
                if args[2] == 'qualify':
                    raise subprocess.CalledProcessError(1, 'MOCK_QUALIFICATION_ONLY')
            with patch.object(window, 'STATE', state), patch.object(window, 'command', side_effect=child), patch('sys.argv', ['window', 'run', '--window', 'fixture', '--approved-plan-sha256', window.sha(plan)]):
                with self.assertRaises(subprocess.CalledProcessError):
                    window.main()
            self.assertEqual(calls, ['apply', 'qualify', 'destroy'])

    def test_critical_attestation_error_blocks_cuda_even_with_success_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            executables = directory / "bin"
            executables.mkdir()
            fixture = '''#!/usr/bin/env bash
case "$(basename "$0")" in
 nvidia-smi)
  case "$*" in
   *'-f'*) echo 'MOCK FIXTURE ONLY: CC status: ON';;
   *'-e'*) echo 'MOCK FIXTURE ONLY: PRODUCTION';;
   *) echo 'MOCK FIXTURE ONLY';;
  esac;;
 mokutil) echo 'MOCK FIXTURE ONLY: SecureBoot enabled';;
 sudo)
  case "$*" in
   *cpu-attestation*) echo 'MOCK FIXTURE ONLY: Attested Guest Successfully'; exit 2;;
   *gpu-attestation*) echo 'MOCK FIXTURE ONLY: GPU Attestation is Successful';;
   *docker*) echo 'MOCK FIXTURE ONLY: DOCKER_EXECUTED' >> "$CC_EVIDENCE_DIRECTORY/forbidden-execution";;
  esac;;
 python3) echo 'MOCK FIXTURE ONLY: torch unavailable'; exit 77;;
esac
'''
            for name in ["nvidia-smi", "mokutil", "sudo", "python3"]:
                path = executables / name
                path.write_text(fixture)
                path.chmod(0o755)
            evidence = directory / "evidence"
            env = dict(os.environ, PATH=str(executables) + ":/usr/bin:/bin", CC_EVIDENCE_DIRECTORY=str(evidence))
            result = subprocess.run(["bash", str(ROOT / "scripts/qualify-host.sh"), "ghcr.io/ihsenalaya/cc-contract-cuda@sha256:" + "a" * 64], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse((evidence / "forbidden-execution").exists())
            self.assertIn("NOT_RUN_ATTESTATION_OR_CC_GATE", (evidence / "commands.tsv").read_text())


if __name__ == "__main__":
    unittest.main()
