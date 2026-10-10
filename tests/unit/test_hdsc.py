import copy
import hashlib
import unittest

from cc_contract.hdsc_baselines import output_only, cuda_status, sanitizer_result
from cc_contract.hdsc_benchmark import benchmark, packets, schedule
from cc_contract.hdsc_dynamic import run
from cc_contract.hdsc_rq2 import execute
from cc_contract.hdsc_runtime import Ledger
from cc_contract.hdsc_statistics import paired_effect, first_detection, percentile


class HDSCTest(unittest.TestCase):
    def test_splits_and_cause_equivalence(self):
        targets = benchmark()["targets"]
        dev = {x['seed'] for x in targets if x['split'] == 'development'}
        reserved = {x['seed'] for x in targets if x['split'] == 'reserved_evaluation'}
        self.assertFalse(dev & reserved)
        self.assertEqual(len({x['cause_equivalence'] for x in targets}), 4)
        self.assertEqual(len(schedule('reserved_evaluation')), 960)

    def test_reserved_not_used_by_cpu_qualification(self):
        with self.assertRaises(ValueError):
            execute(next(x for x in schedule('reserved_evaluation') if x['tool'] == 'direct'), 'cpu-model', None)

    def test_rq2_payload_equivalence_and_output_collision(self):
        rows = [execute(x, 'cpu-model', None) for x in schedule('development') if x['tool'] == 'direct']
        self.assertEqual(len(rows), 48)
        for row in rows:
            self.assertEqual(row['B0_cuda_status'], 'UNSUPPORTED')
            self.assertEqual(row['B3_CC_Contract']['classification'], 'STATE_CONTINUITY_VIOLATION' if row['active'] else 'PASS')
            alert = row['active'] and row['target']['state_variant'] == 'changed-output'
            self.assertEqual(row['B1_output_only'], 'ALERT' if alert else 'PASS')
        self.assertEqual(sum(x['activated'] for x in rows), 24)

    def test_status_has_no_model_cuda_success(self):
        self.assertEqual(cuda_status({'execution_status':'MODEL_SUCCESS'}), 'UNSUPPORTED')
        self.assertEqual(cuda_status({'execution_status':'CUDA_ERROR'}), 'ALERT')

    def test_output_baseline_no_identity_inputs(self):
        self.assertEqual(output_only(19, 19), 'PASS')
        self.assertEqual(output_only(19, 20), 'ALERT')
        self.assertEqual(output_only(19, None), 'INVALID_TEST')

    def test_sanitizer_never_counts_launch_failure_as_clean(self):
        obs={'execution_status':'CUDA_SUCCESS'}
        self.assertEqual(sanitizer_result('memcheck',0,'','',obs)['classification'],'INFRA_FAILURE')
        self.assertEqual(sanitizer_result('memcheck',1,'','ERROR SUMMARY: 0 errors',obs)['classification'],'INFRA_FAILURE')
        self.assertEqual(sanitizer_result('memcheck',0,'','ERROR SUMMARY: 0 errors',obs)['classification'],'PASS')
        self.assertEqual(sanitizer_result('memcheck',86,'','ERROR SUMMARY: 1 error',obs)['classification'],'ALERT')
        self.assertEqual(sanitizer_result('racecheck',1,'','Not supported under Confidential Computing',obs)['classification'],'UNSUPPORTED')
        self.assertEqual(sanitizer_result('racecheck',86,'','RACECHECK SUMMARY: 2 hazards displayed',obs)['classification'],'ALERT')

    def test_cc_disabled_instrumentation_is_not_a_detection(self):
        # Exact diagnostic observed on the retained CC-ON H100, INC-0122.
        text=('========= COMPUTE-SANITIZER\n'
              '========= Error: Confidential compute mode detected. compute-sanitizer will be disabled.\n'
              '========= ERROR SUMMARY: 1 error\n')
        for tool in ('memcheck','initcheck','synccheck'):
            result=sanitizer_result(tool,86,text,'',{'execution_status':'CUDA_SUCCESS'})
            self.assertEqual(result,{'classification':'UNSUPPORTED','reason':'tool_rejected_environment'})
        unknown=text.replace('Confidential compute mode detected. ','Unexpected environment. ')
        self.assertEqual(sanitizer_result('memcheck',86,unknown,'',{'execution_status':'CUDA_SUCCESS'})['classification'],'INFRA_FAILURE')

    def test_dynamic_healthy_and_all_faults(self):
        for seed in range(82000,82008):
            for fault in (None,'L1','L2','C1','C2'):
                result=run(seed,fault)
                self.assertTrue(4<=len(result['steps'])<=12)
                alerts=[r for r in result['steps'] if r['verdict']['classification']!='PASS']
                self.assertEqual(len(alerts),int(fault is not None))
                self.assertFalse(result['trace_known_to_verifier_in_advance'])

    def test_dynamic_execution_has_distinct_paths(self):
        traces=[run(seed) for seed in range(82000,82008)]
        self.assertGreater(len({len(r['steps']) for r in traces}),1)
        self.assertEqual({s['observation']['consumer'] for r in traces for s in r['steps']},{1,2})
        self.assertGreater(len({s['expected']['buffer_id'] for r in traces for s in r['steps']}),1)

    def ready(self):
        ledger=Ledger()
        expected=ledger.declare(1,1,b'payload','P','S','E','K')
        ledger.transferred('slot',expected);ledger.recorded('E','slot');ledger.waited('T','E')
        return ledger,expected

    def test_pending_reuse_is_rejected(self):
        ledger,expected=self.ready();ledger.launch(expected,'slot','T')
        with self.assertRaises(ValueError): ledger.declare(1,2,b'new','P','S','E2','K')
        with self.assertRaises(ValueError): ledger.transferred('slot',expected)

    def test_generation_and_event_epochs_are_not_names_only(self):
        ledger,expected=self.ready()
        with self.assertRaises(ValueError): ledger.declare(1,1,b'x','P','S','E2','K')
        with self.assertRaises(ValueError): ledger.recorded('E','slot')
        with self.assertRaises(ValueError): ledger.waited('T','unknown')

    def test_same_bytes_wrong_identity_are_detected(self):
        ledger,expected=self.ready();ledger.launch(expected,'slot','T')
        verdict=ledger.complete(expected,'slot','T','MODEL_SUCCESS',b'payload',2,1,'K')
        self.assertEqual(verdict['classification'],'STATE_CONTINUITY_VIOLATION')
        self.assertEqual(verdict['mismatches'],['buffer_id'])

    def test_wrong_dependency_without_payload_error(self):
        ledger,expected=self.ready();ledger.launch(expected,'slot','other-stream')
        verdict=ledger.complete(expected,'slot','other-stream','MODEL_SUCCESS',b'payload',1,1,'K')
        self.assertIn('dependency_binding',verdict['mismatches'])

    def test_graph_binding_is_a_snapshot_of_pointer_not_variable(self):
        ledger,old=self.ready();ledger.captured('G','slot')
        new=ledger.declare(1,2,b'new','P','S','E2','K')
        ledger.transferred('new',new);ledger.recorded('E2','new');ledger.waited('T','E2')
        selected=ledger.launch(new,'new','T',graph='G')
        self.assertEqual(selected,'slot')
        result=ledger.complete(new,selected,'T','MODEL_SUCCESS',b'payload',1,1,'K')
        self.assertEqual(result['classification'],'STATE_CONTINUITY_VIOLATION')

    def test_packet_hashes_and_shared_final_sum(self):
        for profile in ('equal-payload','sum-collision'):
            data=packets(82000,profile)
            self.assertNotEqual(data[0],data[1])
            if profile=='equal-payload':self.assertEqual(data[0][12:],data[1][12:])
            else:self.assertNotEqual(data[0][12:],data[1][12:])

    def test_statistics_preserve_negative_and_undefined_effects(self):
        effect=paired_effect([(10,9),(10,8),(10,7)])
        self.assertEqual(effect['absolute_difference'],-2)
        self.assertLess(effect['absolute_difference_bootstrap_95'][1],0)
        self.assertIsNone(paired_effect([(0,1),(0,2)])['relative_difference_percent'])
        self.assertEqual(percentile([1,3],.5),2)

    def test_censoring_is_not_a_detection(self):
        result=first_detection([{'detected':False}]*5,5)
        self.assertFalse(result['event_observed']);self.assertIsNone(result['candidates_to_detection'])
        self.assertEqual(first_detection([{'detected':False},{'detected':True}],5)['candidates_to_detection'],2)

    def test_no_unjustified_or_parallel_reserved_jobs(self):
        from cc_contract.hdsc_schedule import schedule as planned,counts
        rows=planned(); inventory=counts()
        self.assertEqual(inventory['serial_jobs'],1153)
        self.assertEqual(inventory['workload_requests'],1433)
        self.assertEqual(inventory['AI_model_instances'],70)
        self.assertEqual([r['job_id'] for r in rows],list(range(len(rows))))
        self.assertTrue(all(r['rq'] in ('RQ2','RQ3','RQ2/RQ3','RQ4') for r in rows))
        self.assertFalse(any(r.get('tool')=='racecheck' for r in rows))
        for block in range(10):
            perf=[r for r in rows if r.get('block')==block and r['kind']=='performance']
            self.assertEqual({r['enabled'] for r in perf},{False,True})
            self.assertEqual({(r['seed'],r['warmups'],r['measured_requests']) for r in perf},{(93000+block,3,10)})

    def test_independent_auditor_rejects_changed_verdict(self):
        import importlib.util,json,tempfile
        from pathlib import Path
        path=Path(__file__).resolve().parents[2]/'scripts/audit-hdsc-rq2.py'
        spec=importlib.util.spec_from_file_location('audit_hdsc',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        row=execute(next(x for x in schedule('development') if x['active'] and x['tool']=='direct'),'cpu-model',None)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'runs.jsonl';path.write_text(json.dumps(row)+'\n')
            self.assertEqual(module.audit(path)['rows'],1)
            row['B3_CC_Contract']['classification']='PASS';path.write_text(json.dumps(row)+'\n')
            with self.assertRaises(ValueError):module.audit(path)

    def test_AI_prompts_are_disjoint_without_loading_model(self):
        from cc_contract.hdsc_ai import prompt_for_seed
        groups=[{prompt_for_seed(seed) for seed in seeds} for seeds in
                (range(82000,82008),range(93000,93010),range(104000,104010))]
        self.assertFalse(groups[0]&groups[1] or groups[1]&groups[2] or groups[0]&groups[2])
        self.assertEqual(len(groups[1]),10);self.assertEqual(len(groups[2]),10)


if __name__=='__main__': unittest.main()
