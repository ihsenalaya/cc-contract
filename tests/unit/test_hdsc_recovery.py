"""Offline lifecycle/archive tests; no cloud operations or CUDA execution."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


class RecoveryTest(unittest.TestCase):
    def test_recovery_only_approval_rejects_experiments_reuse_and_source_changes(self):
        c=module('recover-hdsc-window');now=datetime.now(timezone.utc)
        plan={**c.POLICY,'source_files_sha256':c.sources()}
        receipt={k:plan[k] for k in ('protocol','max_minutes','budget_usd','experiment_jobs')}
        receipt.update(approved=True,approved_by='user',plan_sha256='a'*64,
                       reuse_completed_authorization=False,approved_utc=now.isoformat())
        c.validate(plan,receipt,'a'*64,now)
        for key,value in (('experiment_jobs',1),('budget_usd',4),('source_files_sha256',{})):
            with self.assertRaises(ValueError):c.validate({**plan,key:value},receipt,'a'*64,now)
        with self.assertRaises(ValueError):c.validate(plan,{**receipt,'reuse_completed_authorization':True},'a'*64,now)
        with self.assertRaises(ValueError):c.validate(plan,receipt,'b'*64,now)

    def test_recovery_only_transport_is_bounded_read_only_and_no_retry(self):
        c=module('recover-hdsc-window')
        with tempfile.TemporaryDirectory() as tmp,patch.object(c.subprocess,'run',side_effect=TimeoutError('transfer failed')) as run:
            with self.assertRaises(TimeoutError):c.transfer(['verified-ssh'],Path(tmp))
            self.assertEqual(run.call_count,1)
            self.assertEqual(run.call_args.args[0],['verified-ssh','sudo -n python3 - --window hdsc-eval-1010b'])
            self.assertEqual(run.call_args.kwargs['timeout'],90)
            self.assertEqual(run.call_args.kwargs['input'],(ROOT/'scripts/hdsc-recovery.py').read_bytes())

    def test_recovery_window_selection_does_not_accept_arbitrary_paths(self):
        helper=module('hdsc-recovery')
        with patch.object(sys,'argv',['helper','--window','hdsc-eval-1010b']), \
             patch.object(helper.subprocess,'check_output',return_value=b''),patch.object(helper,'archive') as archive:
            helper.main()
            self.assertEqual(archive.call_args.args[0],Path('/home/cccontract/cc-hdsc-hdsc-eval-1010b'))
        with patch.object(sys,'argv',['helper','--window','../../foreign']), \
             patch.object(helper.subprocess,'check_output') as commands,patch.object(sys,'stderr',io.StringIO()):
            with self.assertRaises(SystemExit):helper.main()
            commands.assert_not_called()

    def setup_old(self,path):
        (path/'evidence/data/core').mkdir(parents=True)
        (path/'evidence/data/core/jobs.jsonl').write_bytes(b'{"original":true}\n')
        for name in ('plan.json','approval.json','run-hdsc-host.sh','run-hdsc-section.py'):
            (path/name).write_bytes(b'preserved-original')

    def test_running_gpu_or_project_container_refused_without_mutation(self):
        helper=module('hdsc-recovery')
        for host,name in [({'Runtime':'nvidia'},'/other'),({'DeviceRequests':[{'Capabilities':[['gpu']]}]},'/other'),({},'/cc-hdsc-core')]:
            row={'State':{'Running':True},'HostConfig':host,'Name':name}
            with self.assertRaisesRegex(ValueError,'running'):helper.preflight([row])
            row['State']['Running']=False;helper.preflight([row])
        helper.preflight([{'Name':'/unrelated-cpu','State':{'Running':True},'HostConfig':{}}])

    def test_recovery_hashes_preserve_all_originals_and_reject_symlinks(self):
        helper=module('hdsc-recovery');controller=module('hdsc-window')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'old';self.setup_old(old)
            before={str(p.relative_to(old)):p.read_bytes() for p in old.rglob('*') if p.is_file()}
            raw=io.BytesIO();helper.archive(old,[],raw)
            archive=root/'recovery.tar.gz';archive.write_bytes(raw.getvalue());controller.verify_archive(archive,root)
            with tarfile.open(archive) as stream:
                self.assertEqual(stream.extractfile('originals/data/core/jobs.jsonl').read(),b'{"original":true}\n')
            self.assertEqual(before,{str(p.relative_to(old)):p.read_bytes() for p in old.rglob('*') if p.is_file()})
            (old/'evidence/unsafe').symlink_to(old/'plan.json')
            with self.assertRaisesRegex(ValueError,'symlink'):helper.archive(old,[],io.BytesIO())

    def test_recovery_old_plan_and_snapshot_are_verified_before_admission(self):
        helper=module('hdsc-recovery');controller=module('hdsc-window')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'old';self.setup_old(old);raw=io.BytesIO();helper.archive(old,[],raw)
            policy=dict(previous_plan_sha256=hashlib.sha256(b'preserved-original').hexdigest(),captured_prefix_rows=1,
                        captured_prefix_sha256=hashlib.sha256(b'{"original":true}\n').hexdigest())
            def transport(*args,**kwargs):kwargs['stdout'].write(raw.getvalue())
            for altered in (None,'previous_plan_sha256','captured_prefix_sha256'):
                directory=root/str(altered);directory.mkdir();p=dict(policy)
                if altered:p[altered]='0'*64
                with patch.object(controller.subprocess,'run',side_effect=transport):
                    if altered:
                        with self.assertRaisesRegex(ValueError,'disagrees'):controller.recover_previous(['ssh'],directory,p)
                    else:controller.recover_previous(['ssh'],directory,p)
                self.assertEqual((directory/'recovered-previous/provenance.json').exists(),altered is None)

    def test_smaller_window_requires_matching_budget_and_recovery_policy(self):
        from cc_contract.hdsc_schedule import counts
        c=module('hdsc-window');now=datetime.now(timezone.utc)
        plan=dict(protocol='hdsc-evaluation-v1',vm_id=c.retained.VM,vm_uuid=c.retained.UUID,disk_uuid=c.retained.DISK_UUID,
            counts=counts(),max_minutes=30,budget_usd=4,gpu_parallelism=1,creates=0,destroys=0,resumption=c.RESUME,
            images={s:'ghcr.io/ihsenalaya/cc-contract-hdsc'+('-ai' if s=='ai' else '')+'@sha256:'+'a'*64 for s in ('core','ai')},
            source_files_sha256={str(p.relative_to(ROOT)):c.sha(p) for p in c.source_files()},schedule_sha256=c.sha(ROOT/'experiments/hdsc-schedule-v1.json'))
        receipt=dict(approved=True,approved_by='user',plan_sha256='b'*64,protocol=plan['protocol'],max_minutes=30,
            budget_usd=4,reuse_completed_authorization=False,approved_utc=now.isoformat())
        c.approval(plan,receipt,'b'*64,now)
        for altered in ({'budget_usd':12},{'max_minutes':90}):
            with self.assertRaises(ValueError):c.approval(plan,{**receipt,**altered},'b'*64,now)
        with self.assertRaises(ValueError):c.check_plan({**plan,'resumption':{}})

    def test_unsupported_reserved_rows_never_launch_and_healthy_alert_stops(self):
        runner=module('run-hdsc-section')
        cap=dict(job_id=0,kind='capability',tool='memcheck',section='core',maximum_seconds=30)
        dependent=dict(job_id=1,kind='rq2',tool='memcheck',section='core',maximum_seconds=30)
        for classification in ('UNSUPPORTED','ALERT','PASS'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'plan').write_bytes(b'{}');(root/'approval').write_text('{}')
                result={'B2_sanitizer':{'classification':classification,'reason':'tool_rejected_environment'},
                        'B3_CC_Contract':{'classification':'PASS'},'observation':{'execution_status':'CUDA_SUCCESS'}}
                argv=['runner','--section','core','--output',str(root/'out'),'--plan',str(root/'plan'),'--approval',str(root/'approval')]
                with patch.object(sys,'argv',argv),patch.object(runner,'schedule',return_value=[cap,dependent]), \
                     patch.object(runner,'validate_inputs',return_value=({'resumption':{'expected_unsupported_tools':['memcheck']}},datetime.now(timezone.utc)+timedelta(minutes=10))), \
                     patch.object(runner,'run_job',return_value=result) as run:
                    if classification=='UNSUPPORTED':runner.main()
                    else:
                        with self.assertRaises(RuntimeError):runner.main()
                self.assertEqual(run.call_count,1)
                rows=[json.loads(s) for s in (root/'out/jobs.jsonl').read_text().splitlines()]
                self.assertEqual(len(rows),2 if classification=='UNSUPPORTED' else 1)
                if classification=='UNSUPPORTED':self.assertFalse(rows[1]['result']['executed'])

    def test_skipped_jobs_require_original_preceding_tool_rejection(self):
        analyzer=module('analyze-hdsc-evaluation')
        cap={'job':{'kind':'capability','tool':'memcheck'},'result':{'tool':'memcheck',
            'B2_sanitizer':{'classification':'UNSUPPORTED'},'observation':{},
            'raw_worker':{'stdout':'Confidential compute mode detected. compute-sanitizer will be disabled.','stderr':'','returncode':86}}}
        skipped={'job':{'kind':'rq2','tool':'memcheck'},'result':{'classification':'UNSUPPORTED',
            'reason':'capability_rejected_environment','executed':False}}
        self.assertEqual(analyzer.audit_admission([cap,skipped]),['memcheck'])
        with self.assertRaises(ValueError):analyzer.audit_admission([skipped,cap])
        cap['result']['raw_worker']['stdout']='ERROR SUMMARY: 0 errors'
        with self.assertRaises(ValueError):analyzer.audit_admission([cap,skipped])


if __name__=='__main__':unittest.main()
