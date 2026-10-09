"""CPU-only control-flow checks for a retained VM campaign; no cloud access."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
loader=importlib.util.spec_from_file_location('fixed_work_cloud',ROOT/'scripts/azure-window.py')
window=importlib.util.module_from_spec(loader);loader.loader.exec_module(window)


class FixedWorkCloudTests(unittest.TestCase):
    def test_resumed_guest_root_is_fresh_and_identity_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'fixed-work-fixture';directory.mkdir()
            old='/home/cccontract/cc-contract-evidence'
            self.assertEqual(window.remote_evidence_directory(directory),old)
            bundle={'transport':'FIXED_WORK_IR_CAMPAIGN','campaign_id':directory.name}
            path=directory/'workload-bundle.json';path.write_text(json.dumps(bundle))
            expected='/home/cccontract/cc-campaigns/'+directory.name+'/cc-contract-evidence'
            self.assertEqual(window.remote_evidence_directory(directory),expected)
            for identity in ('another-campaign','../outside','name;touch-secret'):
                bundle['campaign_id']=identity;path.write_text(json.dumps(bundle))
                with self.assertRaisesRegex(ValueError,'identity differs'):
                    window.remote_evidence_directory(directory)

    def test_download_success_and_byte_cap_failure_preserve_partials_and_release(self):
        for oversized in (False,True):
            with self.subTest(oversized=oversized),tempfile.TemporaryDirectory() as temporary:
                directory=Path(temporary)/'fixed-work-fixture';directory.mkdir()
                bundle={'transport':'FIXED_WORK_IR_CAMPAIGN','campaign_id':directory.name,
                        'archive_download_byte_limit':16}
                (directory/'workload-bundle.json').write_text(json.dumps(bundle))
                class Producer:
                    def __init__(self):
                        read_fd,write_fd=os.pipe()
                        os.write(write_fd,b'CPU ARCHIVE' if not oversized else b'x'*17)
                        os.close(write_fd)
                        self.stdout=os.fdopen(read_fd,'rb')
                        self.killed=False
                    def wait(self,timeout=None):return 0
                    def poll(self):return None if oversized and not self.killed else 0
                    def kill(self):self.killed=True
                producer=Producer()
                with patch.object(window,'ARCHIVE_DOWNLOAD_BYTE_LIMIT',16), \
                     patch.object(window,'ensure_window',return_value=({},{})), \
                     patch.object(window,'ssh_args',return_value=['CPU_ONLY_EXPORT_FIXTURE']), \
                     patch.object(window.subprocess,'Popen',return_value=producer) as started, \
                     patch.object(window,'verify_evidence_archive',return_value=1), \
                     patch.object(window,'release') as release,patch.object(window,'tf') as terraform:
                    if oversized:
                        with self.assertRaisesRegex(ValueError,'byte bound'):
                            window.collect_and_release(directory)
                        self.assertTrue(producer.killed)
                        self.assertFalse((directory/'collection.json').exists())
                    else:
                        window.collect_and_release(directory)
                        result=json.loads((directory/'collection.json').read_text())
                        self.assertEqual(result['files_verified'],1)
                        self.assertIn('/cc-campaigns/fixed-work-fixture/',result['remote_evidence_directory'])
                    release.assert_called_once_with(directory);terraform.assert_not_called()
                    self.assertIn('gzip -1',started.call_args.args[0][-1])
                    self.assertEqual(len(list(directory.glob('guest-evidence-*.tar.gz'))),1)
                    self.assertTrue(producer.stdout.closed)

    def test_stalled_pipe_deadline_still_stops_producer_and_releases_compute(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'fixed-work-fixture';directory.mkdir()
            (directory/'workload-bundle.json').write_text(json.dumps({
                'transport':'FIXED_WORK_IR_CAMPAIGN','campaign_id':directory.name,
                'archive_download_byte_limit':window.ARCHIVE_DOWNLOAD_BYTE_LIMIT}))
            read_fd,write_fd=os.pipe()
            class Producer:
                def __init__(self):self.stdout=os.fdopen(read_fd,'rb');self.killed=False
                def poll(self):return 0 if self.killed else None
                def wait(self,timeout=None):return 0
                def kill(self):self.killed=True;os.close(write_fd)
            producer=Producer()
            with patch.object(window,'ARCHIVE_DOWNLOAD_TIMEOUT_SECONDS',0.02), \
                 patch.object(window,'ensure_window',return_value=({},{})), \
                 patch.object(window,'ssh_args',return_value=['CPU_ONLY_STALLED_EXPORT']), \
                 patch.object(window.subprocess,'Popen',return_value=producer), \
                 patch.object(window,'release') as release:
                with self.assertRaisesRegex(TimeoutError,'deadline'):
                    window.collect_and_release(directory)
                release.assert_called_once_with(directory)
                self.assertTrue(producer.killed)
                self.assertTrue(producer.stdout.closed)
                self.assertFalse((directory/'collection.json').exists())

    def test_host_campaign_mount_hash_and_gate_block_later_gpu_jobs(self):
        for failure in ('none','helper','ir'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as temporary:
                directory=Path(temporary);executables=directory/'bin';executables.mkdir()
                # These outputs are explicit CPU fixtures. They cannot attest hardware.
                fixture='''#!/usr/bin/env bash
case "$(basename "$0")" in
 uname) [[ "$*" != '-r' ]] || echo '6.8.0-1066-azure-fde';;
 mokutil) echo 'CPU FIXTURE ONLY SecureBoot enabled';;
 nvidia-smi)
  case "$*" in
   *--query-gpu=driver_version*) echo '595.91.07';;
   *-f*) echo 'CPU FIXTURE ONLY CC status: ON';;
   *-e*) echo 'CPU FIXTURE ONLY PRODUCTION';;
  esac;;
 sudo)
  case "$*" in
   *cpu-attestation*) echo 'CPU FIXTURE ONLY Attested Guest Successfully';;
   *gpu-attestation*) echo 'CPU FIXTURE ONLY GPU Attestation is Successful';;
   *'docker image inspect'*) echo 'e8f34fddc62479a6995dcf260a4242e1494cc26b';;
   *'qualify --backend cuda'*) [[ "$CC_FIXTURE_FAILURE" != ir ]] || exit 77;;
   *'/run-fixed-work-campaign.py'*) printf '%s\\n' "$*" > "$CC_EVIDENCE_DIRECTORY/executed-command";;
  esac;;
esac
'''
                for name in ('uname','mokutil','nvidia-smi','sudo'):
                    path=executables/name;path.write_text(fixture);path.chmod(0o755)
                sources=[]
                for name in ('spec.json','wrapper.py','helper.py'):
                    path=directory/name;path.write_text('CPU FIXTURE ORIGINAL '+name);sources.append(path)
                spec,wrapper,helper=sources
                evidence=directory/'new-evidence'
                environment={**os.environ,'PATH':str(executables)+':/usr/bin:/bin',
                    'CC_EVIDENCE_DIRECTORY':str(evidence),'CC_FIXTURE_FAILURE':failure}
                helper_sha='0'*64 if failure=='helper' else window.sha(helper)
                result=subprocess.run(['bash',str(ROOT/'scripts/qualify-host.sh'),
                    'ghcr.io/ihsenalaya/cc-contract-cuda@sha256:'+'a'*64,
                    'ghcr.io/ihsenalaya/cc-contract-ir@sha256:'+'b'*64,'','','',
                    str(spec),str(wrapper),window.sha(spec),window.sha(wrapper),'campaign',
                    str(helper),helper_sha],env=environment,capture_output=True,text=True,timeout=20)
                executed=evidence/'executed-command'
                if failure=='none':
                    self.assertEqual(result.returncode,0,result.stderr)
                    command=executed.read_text()
                    self.assertIn('target=/run-work-sample.py,readonly',command)
                    self.assertIn('target=/run-fixed-work-campaign.py,readonly',command)
                    self.assertNotIn('cc-contract-torch',command)
                    self.assertIn('fixed-work-campaign\t0',(evidence/'commands.tsv').read_text())
                else:
                    self.assertNotEqual(result.returncode,0)
                    self.assertFalse(executed.exists())
                self.assertFalse((evidence/'python-torch.stdout').exists())

    def test_new_transport_transfers_all_hash_bound_inputs_and_keeps_old_guest_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);state=root/'state';directory=state/'fixed-work-fixture'
            directory.mkdir(parents=True);scripts=root/'scripts';scripts.mkdir()
            (root/'.local/cuda').mkdir(parents=True)
            image='ghcr.io/ihsenalaya/cc-contract-cuda@sha256:'+'a'*64
            (root/'.local/cuda/remote-digest').write_text(image)
            (root/'.config/gh').mkdir(parents=True)
            (root/'.config/gh/hosts.yml').write_text('ghcr.io:\n  oauth_token: CPU_FIXTURE_ONLY_NOT_A_CREDENTIAL\n')
            bundle={'transport':'FIXED_WORK_IR_CAMPAIGN','campaign_id':directory.name,
                    'images':{'cuda':image,'ir':'ghcr.io/ihsenalaya/cc-contract-ir@sha256:'+'b'*64}}
            files={'campaign_spec':root/'spec.json','campaign_harness':scripts/'run-fixed-work-campaign.py',
                   'helper_harness':scripts/'run-work-sample.py','protocol':root/'protocol.md',
                   'reserved_schedule':root/'schedule.json'}
            for name,path in files.items():
                path.write_text('CPU FIXTURE ONLY '+name);bundle[name+'_path']=str(path)
                bundle[name+'_sha256']=window.sha(path)
            host=scripts/'qualify-host.sh';host.write_text('CPU FIXTURE HOST SCRIPT ONLY\n')
            (directory/'workload-bundle.json').write_text(json.dumps(bundle))
            scope={'workload_bundle_sha256':window.sha(directory/'workload-bundle.json'),
                   'host_script_sha256':window.sha(host)}
            (directory/'approved-workload-plan.json').write_text(json.dumps(scope))
            with patch.object(window,'ROOT',root),patch.object(window,'STATE',state), \
                 patch.object(window.Path,'home',return_value=root), \
                 patch.object(window,'ensure_window',return_value=({},{})), \
                 patch.object(window,'verify_bundle',return_value=bundle), \
                 patch.object(window,'ssh_args',return_value=['CPU_FIXTURE_SSH']), \
                 patch.object(window,'command') as transfer, \
                 patch.object(window.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as host_run, \
                 patch.object(window,'collect_and_release') as release, \
                 patch('sys.argv',['window','qualify','--window',directory.name]):
                self.assertEqual(window.main(),0)
                release.assert_called_once_with(directory)
                passed=host_run.call_args.args[0][-1]
                self.assertIn('CC_EVIDENCE_DIRECTORY=/home/cccontract/cc-campaigns/'+directory.name,passed)
                self.assertIn(' campaign ',passed)
                self.assertEqual(host_run.call_args.kwargs['timeout'],3900)
                commands=[call.args[0][-1] for call in transfer.call_args_list]
                self.assertIn('test ! -e',commands[0])
                self.assertTrue(all('~/cc-contract-evidence' not in command for command in commands))
                actual={call.kwargs['input'] for call in transfer.call_args_list
                        if 'input' in call.kwargs and call.kwargs['input'].startswith('CPU FIXTURE ONLY ')}
                self.assertEqual(actual,{path.read_text() for path in files.values()})


if __name__=='__main__':unittest.main()
