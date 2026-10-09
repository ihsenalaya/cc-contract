"""Control-flow tests with explicit CPU fixtures; no hardware evidence."""
import importlib.util
import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("window", ROOT / "scripts/azure-window.py")
window = importlib.util.module_from_spec(spec)
spec.loader.exec_module(window)
spec=importlib.util.spec_from_file_location('model_transport',ROOT/'scripts/model_bundle.py')
model_transport=importlib.util.module_from_spec(spec);spec.loader.exec_module(model_transport)
spec=importlib.util.spec_from_file_location('registry_auth',ROOT/'scripts/with-ghcr-auth.py')
registry_auth=importlib.util.module_from_spec(spec);spec.loader.exec_module(registry_auth)


class InfrastructureTests(unittest.TestCase):
    def test_workload_binding_is_checked_against_saved_binary_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);bundle=directory/'workload-bundle.json';bundle.write_text('{}')
            expected={'workload_bundle_sha256':window.sha(bundle),
                      'host_script_sha256':window.sha(ROOT/'scripts/qualify-host.sh')}
            inputs={'workload_sha256':expected['workload_bundle_sha256'],
                    'host_script_sha256':expected['host_script_sha256']}
            (directory/'inputs.json').write_text(json.dumps(inputs))
            with patch.object(window.subprocess,'check_output') as called:
                with self.assertRaisesRegex(ValueError,'approval bindings missing'):
                    window.verify_workload_plan(directory)
                called.assert_not_called()
            (directory/'approved-workload-plan.json').write_text(json.dumps(expected))
            saved={'variables':{name:{'value':value} for name,value in inputs.items()}}
            with patch.object(window,'verify_bundle',return_value={'transport':'CPU_FIXTURE_ONLY'}), \
                 patch.object(window.subprocess,'check_output',return_value=json.dumps(saved)):
                self.assertEqual(window.verify_workload_plan(directory)['transport'],'CPU_FIXTURE_ONLY')
                saved['variables']['workload_sha256']['value']='0'*64
                with patch.object(window.subprocess,'check_output',return_value=json.dumps(saved)):
                    with self.assertRaisesRegex(ValueError,'Saved Terraform plan'):
                        window.verify_workload_plan(directory)

    def test_sequential_sample_binds_spec_harness_and_excludes_model_images(self):
        import copy
        sample_spec=importlib.util.spec_from_file_location('sample_fixture',ROOT/'scripts/run-sequential-sample.py')
        sample=importlib.util.module_from_spec(sample_spec);sample_spec.loader.exec_module(sample)
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);spec_path=directory/'spec.json'
            spec_path.write_text(json.dumps(sample.make_spec('cuda')))
            bundle={'transport':'SEQUENTIAL_IR_SAMPLE',
                    'images':{'cuda':'ghcr.io/ihsenalaya/cc-contract-cuda@sha256:'+'a'*64,'ir':sample.IMAGE_DIGEST},
                    'sample_spec_path':str(spec_path),'sample_spec_sha256':window.sha(spec_path),
                    'sample_harness_sha256':sample.harness_sha256()}
            path=directory/'bundle.json';path.write_text(json.dumps(bundle))
            self.assertEqual(window.verify_bundle(path)['transport'],'SEQUENTIAL_IR_SAMPLE')
            changed=copy.deepcopy(bundle);changed['images']['torch']='ghcr.io/ihsenalaya/cc-contract-torch@sha256:'+'b'*64
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'only CUDA and IR'):
                window.verify_bundle(path)
            changed=copy.deepcopy(bundle);changed['sample_harness_sha256']='0'*64
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'harness changed'):
                window.verify_bundle(path)
            path.write_text(json.dumps(bundle));spec=json.loads(spec_path.read_text())
            spec['schedule'][0]['budget_seconds']=30;spec_path.write_text(json.dumps(spec))
            with self.assertRaisesRegex(ValueError,'specification changed'):
                window.verify_bundle(path)
            bundle['sample_spec_sha256']=window.sha(spec_path);path.write_text(json.dumps(bundle))
            with self.assertRaisesRegex(ValueError,'schedule, limits or provenance'):
                window.verify_bundle(path)

    def test_finite_work_sample_binds_exact_work_without_model_images(self):
        import copy
        module_spec=importlib.util.spec_from_file_location('work_sample_fixture',ROOT/'scripts/run-work-sample.py')
        sample=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(sample)
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);spec_path=directory/'spec.json'
            spec_path.write_text(json.dumps(sample.make_spec('cuda')))
            bundle={'transport':'FINITE_WORK_IR_SAMPLE',
                    'images':{'cuda':'ghcr.io/ihsenalaya/cc-contract-cuda@sha256:'+'a'*64,'ir':sample.IMAGE_DIGEST},
                    'sample_spec_path':str(spec_path),'sample_spec_sha256':window.sha(spec_path),
                    'sample_harness_sha256':sample.harness_sha256()}
            for name in ('cpu_kind_receipt','independent_cpu_review','volume_preflight',
                         'volume_preflight_source_binding'):
                fixture=directory/(name+'.json');fixture.write_text('{"scope":"CPU_FIXTURE_ONLY"}')
                bundle[name+'_path']=str(fixture);bundle[name+'_sha256']=window.sha(fixture)
            path=directory/'bundle.json';path.write_text(json.dumps(bundle))
            self.assertEqual(window.verify_bundle(path)['transport'],'FINITE_WORK_IR_SAMPLE')
            changed=copy.deepcopy(bundle);changed['volume_preflight_sha256']='0'*64
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'local gate changed'):
                window.verify_bundle(path)
            changed=copy.deepcopy(bundle);del changed['independent_cpu_review_path']
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'local gate binding missing'):
                window.verify_bundle(path)
            changed=copy.deepcopy(bundle);changed['images']['torch']='ghcr.io/ihsenalaya/cc-contract-torch@sha256:'+'b'*64
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'only CUDA and IR'):
                window.verify_bundle(path)
            changed=copy.deepcopy(bundle);changed['sample_harness_sha256']='0'*64
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'harness changed'):
                window.verify_bundle(path)
            spec=json.loads(spec_path.read_text());spec['selected_case_target']=99
            spec_path.write_text(json.dumps(spec));bundle['sample_spec_sha256']=window.sha(spec_path)
            path.write_text(json.dumps(bundle))
            with self.assertRaisesRegex(ValueError,'schedule, limits or provenance'):
                window.verify_bundle(path)

    def test_applied_identity_is_preserved_for_post_cleanup_review_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            resource={'type':'azurerm_linux_virtual_machine','name':'gpu','instances':[
                {'attributes':{'virtual_machine_id':'12345678-1234-1234-1234-123456789abc'}}]}
            original=json.dumps({'resources':[resource]}).encode()
            (directory/'terraform.tfstate').write_bytes(original)
            window.preserve_applied_identity(directory)
            (directory/'terraform.tfstate').write_text('{"resources":[]}')
            self.assertEqual((directory/'tfstate-after-apply.json').read_bytes(),original)
            self.assertEqual(json.loads((directory/'vm-identity.json').read_text()),[resource])
            with self.assertRaisesRegex(ValueError,'identity missing'):
                window.preserve_applied_identity(directory)
            (directory/'terraform.tfstate').write_bytes(original)
            with self.assertRaises(FileExistsError):window.preserve_applied_identity(directory)

    def test_cloud_bundle_rejects_mutable_transport_changed_reader_and_missing_shard(self):
        # CPU-only approval guard fixtures, without network, model bytes or GPU.
        import copy
        names=['cc-model-manifest.json','inference-corpus.json']
        names += [f'model-{n}.safetensors' for n in range(4)]
        names += [f'metadata-{n}.json' for n in range(8)]
        rows=[{'name':n,'blob':'a'*64+'/'+n,'sha256':'a'*64,'bytes':1} for n in names]
        bundle={'transport':'AZURE_BLOB_IMDS',
                'images':{k:'ghcr.io/ihsenalaya/cc-contract-'+k+'@sha256:'+'a'*64 for k in ('cuda','ir','torch')},
                'cloud_transport_image':'ghcr.io/ihsenalaya/cc-contract-cpu@sha256:'+'b'*64,
                'model_cloud':{'account':'cccontractabcdefghij','container':'models','files':rows},
                'cloud_downloader_sha256':window.sha(ROOT/'src/cc_contract/cloud_model.py'),
                'model_manifest_sha256':'a'*64,'corpus_sha256':'a'*64,
                'corpus_filename':'inference-corpus.json','model_revision':'a09a35458c702b33eeacc393d103063234e8bc28'}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bundle.json';path.write_text(json.dumps(bundle))
            window.verify_bundle(path)
            for field,value,message in [
                ('cloud_transport_image','ghcr.io/ihsenalaya/cc-contract-cpu:latest','immutable'),
                ('cloud_downloader_sha256','0'*64,'changed')]:
                mutated=copy.deepcopy(bundle);mutated[field]=value;path.write_text(json.dumps(mutated))
                with self.assertRaisesRegex(ValueError,message):window.verify_bundle(path)
            mutated=copy.deepcopy(bundle);mutated['model_cloud']['files'].pop(2)
            path.write_text(json.dumps(mutated))
            with self.assertRaisesRegex(ValueError,'incomplete'):window.verify_bundle(path)

    def test_temporary_registry_credential_is_removed_when_child_fails(self):
        observed=[]
        def command(args,**kwargs):
            directory=Path(kwargs['env']['DOCKER_CONFIG']);observed.append(directory)
            self.assertEqual(directory.stat().st_mode & 0o777,0o700)
            if args[0]=='docker':
                (directory/'config.json').write_text('CPU_CREDENTIAL_FIXTURE')
                return subprocess.CompletedProcess(args,0)
            raise RuntimeError('controlled child failure')
        with patch.dict(os.environ,{'GH_TOKEN':'CPU_CREDENTIAL_FIXTURE'}), \
             patch.object(sys,'argv',['with-ghcr-auth.py','CPU_COMMAND_FIXTURE']), \
             patch.object(registry_auth.subprocess,'run',side_effect=command):
            with self.assertRaisesRegex(RuntimeError,'controlled child'):
                registry_auth.main()
        self.assertTrue(observed)
        self.assertTrue(all(not p.exists() for p in observed))

    def test_deterministic_stream_preserves_bytes_and_rejects_changed_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);data=directory/'fixture.safetensors';data.write_bytes(b'CPU_DATA_FIXTURE'*1000)
            manifest=directory/'cc-model-manifest.json'
            manifest.write_text(json.dumps({'file_sha256':{data.name:hashlib.sha256(data.read_bytes()).hexdigest()}}))
            corpus=directory/'corpus.json';corpus.write_text('[]')
            first=io.BytesIO();expected=model_transport.stream(directory,corpus,first)
            os.utime(data,(123,123))
            second=io.BytesIO();repeated=model_transport.stream(directory,corpus,second)
            self.assertEqual(expected,repeated);self.assertEqual(first.getvalue(),second.getvalue())
            with tarfile.open(fileobj=io.BytesIO(first.getvalue())) as archive:
                self.assertEqual(set(archive.getnames()),{data.name,manifest.name,'inference-corpus.json'})
                self.assertEqual(archive.extractfile(data.name).read(),data.read_bytes())
            bundle={'transport':'DETERMINISTIC_TAR_STREAM','model_directory':str(directory),'corpus_path':str(corpus),
                    'model_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
                    'corpus_sha256':hashlib.sha256(corpus.read_bytes()).hexdigest(),
                    'images':{k:'ghcr.io/ihsenalaya/cc-contract-'+k+'@sha256:'+'a'*64 for k in ('cuda','ir','torch')},
                    'corpus_filename':'inference-corpus.json','model_revision':'a09a35458c702b33eeacc393d103063234e8bc28',
                    'model_archive_sha256':expected['sha256'],'model_archive_bytes':expected['bytes']}
            path=directory/'bundle.json';path.write_text(json.dumps(bundle))
            window.verify_bundle(path)
            result=subprocess.run(['python3',str(ROOT/'scripts/stream-model-bundle.py'),'--bundle',str(path)],capture_output=True,check=True)
            self.assertEqual(result.stdout,first.getvalue())
            data.write_bytes(b'CHANGED_CPU_DATA_FIXTURE')
            with self.assertRaisesRegex(ValueError,'model data changed'):window.verify_bundle(path)

    def test_prepared_bundle_rejects_changed_archive_and_mutable_images(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);archive=directory/'model.tar.gz';archive.write_bytes(b'CPU_MODEL_ARCHIVE_FIXTURE')
            bundle={'images':{k:'ghcr.io/ihsenalaya/cc-contract-'+k+'@sha256:'+'a'*64 for k in ('cuda','ir','torch')},
                    'model_archive':str(archive),'model_archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                    'corpus_filename':'inference-corpus.json','model_revision':'a09a35458c702b33eeacc393d103063234e8bc28'}
            path=directory/'bundle.json';path.write_text(json.dumps(bundle))
            self.assertEqual(window.verify_bundle(path)['model_archive_sha256'],bundle['model_archive_sha256'])
            archive.write_bytes(b'CHANGED_CPU_FIXTURE')
            with self.assertRaisesRegex(ValueError,'archive hash'):window.verify_bundle(path)
            bundle['images']['ir']='ghcr.io/ihsenalaya/cc-contract-ir:latest';path.write_text(json.dumps(bundle))
            with self.assertRaisesRegex(ValueError,'immutable'):window.verify_bundle(path)

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
            phases=[json.loads(line) for line in (directory/'run-phases.jsonl').read_text().splitlines()]
            self.assertEqual([(p['phase'],p['state']) for p in phases],
                [('apply','STARTED'),('apply','FINISHED'),('qualify_collect_release','STARTED'),
                 ('qualify_collect_release','FAILED'),('destroy','STARTED'),('destroy','FINISHED')])
            result=json.loads((directory/'run-exit.json').read_text())
            self.assertEqual(result['error_type'],'CalledProcessError')
            self.assertGreaterEqual(result['elapsed_seconds'],sum(p.get('elapsed_seconds',0) for p in phases))
            self.assertFalse(result['analysis_and_user_decision_time_included'])

    def test_critical_attestation_error_blocks_cuda_even_with_success_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            executables = directory / "bin"
            executables.mkdir()
            fixture = '''#!/usr/bin/env bash
case "$(basename "$0")" in
 nvidia-smi)
  case "$*" in
   *'--query-gpu=driver_version'*) echo '595.91.07';;
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
 uname)
  case "$*" in
   '-r') echo '6.8.0-1066-azure-fde';;
   *) echo 'MOCK FIXTURE ONLY';;
  esac;;
esac
'''
            for name in ["nvidia-smi", "mokutil", "sudo", "python3", "uname"]:
                path = executables / name
                path.write_text(fixture)
                path.chmod(0o755)
            evidence = directory / "evidence"
            env = dict(os.environ, PATH=str(executables) + ":/usr/bin:/bin", CC_EVIDENCE_DIRECTORY=str(evidence))
            result = subprocess.run(["bash", str(ROOT / "scripts/qualify-host.sh"), "ghcr.io/ihsenalaya/cc-contract-cuda@sha256:" + "a" * 64], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse((evidence / "forbidden-execution").exists())
            self.assertEqual((evidence / 'driver-version.stdout').read_text().strip(), '595.91.07')
            self.assertEqual((evidence / 'kernel-version.stdout').read_text().strip(), '6.8.0-1066-azure-fde')
            self.assertIn("NOT_RUN_ATTESTATION_OR_CC_GATE", (evidence / "commands.tsv").read_text())

            # The extended image bundle must retain the same fail-closed gate.
            extended = directory / 'extended-evidence'
            env['CC_EVIDENCE_DIRECTORY'] = str(extended)
            result = subprocess.run(['bash',str(ROOT/'scripts/qualify-host.sh'),
                'ghcr.io/ihsenalaya/cc-contract-cuda@sha256:'+'a'*64,
                'ghcr.io/ihsenalaya/cc-contract-ir@sha256:'+'b'*64,
                'ghcr.io/ihsenalaya/cc-contract-torch@sha256:'+'c'*64,
                '/MOCK_MODEL_NOT_USED','corpus.json'],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertFalse((extended/'forbidden-execution').exists())

            # IR-only diagnostic mode may skip Torch, never the critical host gate.
            sample_evidence=directory/'sample-evidence';env['CC_EVIDENCE_DIRECTORY']=str(sample_evidence)
            result=subprocess.run(['bash',str(ROOT/'scripts/qualify-host.sh'),
                'ghcr.io/ihsenalaya/cc-contract-cuda@sha256:'+'a'*64,
                'ghcr.io/ihsenalaya/cc-contract-ir@sha256:'+'b'*64,'','','',
                '/MOCK_SPEC_NOT_USED','/MOCK_HARNESS_NOT_USED','c'*64,'d'*64],
                env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertFalse((sample_evidence/'forbidden-execution').exists())
            self.assertFalse((sample_evidence/'python-torch.stdout').exists())
            self.assertIn('NOT_RUN_ATTESTATION_OR_CC_GATE',(sample_evidence/'commands.tsv').read_text())

    def test_incomplete_ir_qualification_blocks_sequential_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);executables=directory/'bin';executables.mkdir()
            fixture='''#!/usr/bin/env bash
case "$(basename "$0")" in
 nvidia-smi)
  case "$*" in
   *'--query-gpu=driver_version'*) echo '595.91.07';;
   *'-f'*) echo 'MOCK FIXTURE ONLY: CC status: ON';;
   *'-e'*) echo 'MOCK FIXTURE ONLY: PRODUCTION';;
   *) echo 'MOCK FIXTURE ONLY';;
  esac;;
 mokutil) echo 'MOCK FIXTURE ONLY: SecureBoot enabled';;
 uname)
  case "$*" in '-r') echo '6.8.0-1066-azure-fde';; *) echo 'MOCK FIXTURE ONLY';; esac;;
 sudo)
  case "$*" in
   *cpu-attestation*) echo 'MOCK FIXTURE ONLY: Attested Guest Successfully';;
   *gpu-attestation*) echo 'MOCK FIXTURE ONLY: GPU Attestation is Successful';;
   *'docker image inspect'*) echo 'e8f34fddc62479a6995dcf260a4242e1494cc26b';;
   *'qualify --backend cuda'*)
    if [[ "$*" == *'--allow-unsupported'* ]]; then
     echo 'MOCK FIXTURE ONLY: unsupported incorrectly tolerated'; exit 0
    fi
    echo 'MOCK FIXTURE ONLY: unsupported IR'; exit 77;;
   *'/run-sequential-sample.py'*|*'/run-work-sample.py'*) echo 'MOCK FIXTURE ONLY: FORBIDDEN_SAMPLE' > "$CC_EVIDENCE_DIRECTORY/forbidden-execution";;
  esac;;
esac
'''
            for name in ('nvidia-smi','mokutil','uname','sudo'):
                file=executables/name;file.write_text(fixture);file.chmod(0o755)
            evidence=directory/'evidence'
            env={**os.environ,'PATH':str(executables)+':/usr/bin:/bin','CC_EVIDENCE_DIRECTORY':str(evidence)}
            result=subprocess.run(['bash',str(ROOT/'scripts/qualify-host.sh'),
                'ghcr.io/ihsenalaya/cc-contract-cuda@sha256:'+'a'*64,
                'ghcr.io/ihsenalaya/cc-contract-ir@sha256:'+'b'*64,'','','',
                '/MOCK_SPEC_NOT_USED','/MOCK_HARNESS_NOT_USED','c'*64,'d'*64],
                env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertFalse((evidence/'forbidden-execution').exists())
            self.assertIn('ir-reference\t77',(evidence/'commands.tsv').read_text())
            self.assertTrue((evidence/'timings.tsv').exists())
            work_evidence=directory/'work-evidence'
            env['CC_EVIDENCE_DIRECTORY']=str(work_evidence)
            result=subprocess.run(['bash',str(ROOT/'scripts/qualify-host.sh'),
                'ghcr.io/ihsenalaya/cc-contract-cuda@sha256:'+'a'*64,
                'ghcr.io/ihsenalaya/cc-contract-ir@sha256:'+'b'*64,'','','',
                '/MOCK_SPEC_NOT_USED','/MOCK_HARNESS_NOT_USED','c'*64,'d'*64,'work'],
                env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertFalse((work_evidence/'forbidden-execution').exists())
            self.assertIn('ir-reference\t77',(work_evidence/'commands.tsv').read_text())


if __name__ == "__main__":
    unittest.main()
