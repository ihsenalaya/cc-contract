"""No cloud calls: approval, cleanup and deadline failures are exercised by mocks."""
import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cc_contract.hdsc_dynamic import Device
from cc_contract.hdsc_schedule import schedule, counts

ROOT=Path(__file__).resolve().parents[2]


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


class HDSCWindowTest(unittest.TestCase):
    def test_cleanup_worker_error_is_not_silently_successful(self):
        device=Device('cpu-model',None)
        device.process=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.read();print("cleanup failed");sys.exit(3)'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
        with self.assertRaisesRegex(RuntimeError,'cleanup failed'):device.close()
        self.assertIsNone(device.process)

    def test_clean_worker_eof(self):
        device=Device('cpu-model',None)
        device.process=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.read()'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
        device.close();self.assertIsNone(device.process)

    def test_deallocate_even_when_start_request_errors_or_guest_fails(self):
        controller=module('hdsc-window')
        for failed_start in (False,True):
            calls=[]
            def fake_az(*args):
                calls.append(args[:2])
                if args[:2]==('vm','start') and failed_start:raise RuntimeError('start transport failed')
                if args[:2]==('vm','get-instance-view'):return {'instanceView':{'statuses':[{'code':'PowerState/deallocated'}]}}
            with tempfile.TemporaryDirectory() as tmp,patch.object(controller,'az',side_effect=fake_az):
                with self.assertRaises(RuntimeError):
                    with controller.allocated_window(Path(tmp)):raise RuntimeError('guest failed')
                self.assertEqual(calls,[('vm','start'),('vm','deallocate'),('vm','get-instance-view')])
                self.assertTrue(json.loads((Path(tmp)/'release.json').read_text())['disk_retained'])

    def plan(self,controller):
        return dict(protocol='hdsc-evaluation-v1',vm_id=controller.retained.VM,vm_uuid=controller.retained.UUID,
            disk_uuid=controller.retained.DISK_UUID,counts=counts(),max_minutes=90,budget_usd=12,gpu_parallelism=1,
            creates=0,destroys=0,images={s:'ghcr.io/ihsenalaya/cc-contract-hdsc'+('-ai' if s=='ai' else '')+'@sha256:'+'a'*64 for s in ('core','ai')},
            source_files_sha256={str(p.relative_to(ROOT)):controller.sha(p) for p in controller.source_files()},
            schedule_sha256=controller.sha(ROOT/'experiments/hdsc-schedule-v1.json'))

    def test_no_reuse_or_implicit_approval_and_sources_cannot_drift(self):
        controller=module('hdsc-window');plan=self.plan(controller);now=datetime.now(timezone.utc)
        receipt=dict(approved=True,approved_by='user',plan_sha256='b'*64,protocol='hdsc-evaluation-v1',max_minutes=90,
            budget_usd=12,reuse_completed_authorization=False,approved_utc=now.isoformat())
        controller.approval(plan,receipt,'b'*64,now)
        for key,value in [('approved',False),('reuse_completed_authorization',True),('plan_sha256','c'*64),
                          ('approved_utc',(now-timedelta(hours=2)).isoformat()),('budget_usd',20)]:
            with self.subTest(key=key),self.assertRaises(ValueError):controller.approval(plan,{**receipt,key:value},'b'*64,now)
        plan['source_files_sha256']['scripts/run-hdsc-host.sh']='0'*64
        with self.assertRaises(ValueError):controller.approval(plan,receipt,'b'*64,now)

    def test_guest_refuses_expired_or_mismatched_schedule_without_running_jobs(self):
        runner=module('run-hdsc-section');now=datetime.now(timezone.utc)
        schedule_hash=hashlib.sha256((json.dumps(schedule(),sort_keys=True,indent=2)+'\n').encode()).hexdigest()
        data=json.dumps(dict(protocol='hdsc-evaluation-v1',schedule_sha256=schedule_hash)).encode()
        receipt=dict(explicit_user_approval=True,plan_sha256=hashlib.sha256(data).hexdigest(),expires_utc=(now+timedelta(minutes=10)).isoformat())
        runner.validate_inputs(data,receipt,now)
        with self.assertRaises(ValueError):runner.validate_inputs(data,{**receipt,'expires_utc':now.isoformat()},now)
        with self.assertRaises(ValueError):runner.validate_inputs(data+b' ',receipt,now)
        with self.assertRaises(ValueError):runner.validate_inputs(data,{**receipt,'explicit_user_approval':'yes'},now)

    def test_worker_errors_stop_and_scientific_negative_does_not(self):
        runner=module('run-hdsc-section')
        self.assertTrue(runner.technical_failure({'steps':[{'execution_status':'CUDA_ERROR'}]}))
        self.assertTrue(runner.technical_failure({'B2_sanitizer':{'classification':'INFRA_FAILURE'}}))
        self.assertFalse(runner.technical_failure({'classification':'STATE_CONTINUITY_VIOLATION'}))
        self.assertFalse(runner.technical_failure({'classification':'PASS','activated':False}))
        self.assertFalse(runner.technical_failure({'classification':'UNSUPPORTED','executed':False}))

    def test_offline_report_keeps_missing_runs_and_rejects_changed_order(self):
        analyzer=module('analyze-hdsc-evaluation')
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary);schedule_bytes=(ROOT/'experiments/hdsc-schedule-v1.json').read_bytes()
            (path/'schedule.json').write_bytes(schedule_bytes)
            (path/'plan.json').write_text(json.dumps({'schedule_sha256':hashlib.sha256(schedule_bytes).hexdigest()}))
            result=analyzer.analyze(path,path/'plan.json',path/'schedule.json')
            self.assertEqual(result['state'],'AUDITED_PARTIAL_SCHEDULE')
            self.assertEqual(result['recorded_jobs'],0);self.assertEqual(result['missing_jobs'],1153)
            (path/'core').mkdir()
            (path/'core/jobs.jsonl').write_text(json.dumps({'job':schedule()[1],'result':{}})+'\n')
            with self.assertRaisesRegex(ValueError,'prefix'):analyzer.analyze(path,path/'plan.json',path/'schedule.json')

    def test_offline_sanitizer_audit_rejects_fake_clean_status(self):
        analyzer=module('analyze-hdsc-evaluation')
        row={'tool':'memcheck','B2_sanitizer':{'classification':'PASS'},'observation':{'execution_status':'CUDA_SUCCESS'},
             'raw_worker':{'stdout':'','stderr':'ERROR SUMMARY: 0 errors','returncode':0}}
        analyzer.sanitizer_audit(row)
        row['raw_worker']['returncode']=86
        with self.assertRaises(ValueError):analyzer.sanitizer_audit(row)

    def test_collected_archive_must_match_original_guest_hashes(self):
        import io,tarfile
        controller=module('hdsc-window')
        for tampered in (False,True):
            raw=io.BytesIO();data=b'original observation'
            hashes={'data/result.json':hashlib.sha256(data).hexdigest() if not tampered else '0'*64}
            with tarfile.open(fileobj=raw,mode='w:gz') as archive:
                for name,body in [('data/result.json',data),('hashes.json',json.dumps(hashes).encode())]:
                    info=tarfile.TarInfo(name);info.size=len(body);archive.addfile(info,io.BytesIO(body))
            def transport(*args,**kwargs):kwargs['stdout'].write(raw.getvalue())
            with tempfile.TemporaryDirectory() as temporary,patch.object(controller.subprocess,'run',side_effect=transport):
                if tampered:
                    with self.assertRaisesRegex(ValueError,'guest original'):controller.collect(['ssh'],'/remote',Path(temporary))
                else:
                    controller.collect(['ssh'],'/remote',Path(temporary))
                    self.assertTrue((Path(temporary)/'collection.json').exists())


if __name__=='__main__':unittest.main()
