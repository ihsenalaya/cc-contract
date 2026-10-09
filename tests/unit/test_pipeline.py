import importlib.util
from pathlib import Path
import tempfile
import unittest
from cc_contract.benchmark import paired_benchmark
from cc_contract.runner import campaign,ModelExecutor

root=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('schedule_execution',root/'scripts/execute-schedule.py')
execution=importlib.util.module_from_spec(spec);spec.loader.exec_module(execution)


class PipelineTests(unittest.TestCase):
    def test_resume_only_verifies_complete_immutable_run(self):
        config={'method':'B2','seed':21,'block':0,'budget_seconds':.001}
        with tempfile.TemporaryDirectory() as directory:
            campaign(ModelExecutor(),config,directory)
            found=execution.select_complete(Path(directory),config)
            self.assertIsNotNone(found)
            raw=found.parent/'records.jsonl';raw.chmod(0o600);raw.write_bytes(b'{}\n')
            with self.assertRaisesRegex(ValueError,'changed'):execution.select_complete(Path(directory),config)

    def test_performance_is_conditional_and_cannot_skip_correctness(self):
        # Unit fixtures are CPU callables, not actual intervention evidence.
        paths={name:(lambda x:x) for name in ('initial','conservative','intervention')}
        self.assertEqual(paired_benchmark(list(range(24)),paths,lambda c,o:'PASS',None)['state'],'CONDITIONAL_NOT_APPLICABLE')
        paths['intervention']=lambda x:x+1
        result=paired_benchmark(list(range(24)),paths,lambda c,o:'PASS' if c==o else 'FAIL',
                                {'state':'CHARACTERIZED_REAL_ANOMALY','unit_fixture':True})
        self.assertEqual(result['state'],'BLOCKED_CORRECTNESS')
        self.assertEqual(result['records'],[])

    def test_paired_benchmark_records_all_blocks_and_shared_requests(self):
        paths={name:(lambda x:x) for name in ('initial','conservative','intervention')}
        result=paired_benchmark(list(range(24)),paths,lambda c,o:'PASS' if c==o else 'FAIL',
                                {'state':'CHARACTERIZED_REAL_ANOMALY','unit_fixture':True},blocks=2)
        self.assertEqual(result['state'],'COMPLETE_PAIRED_MEASUREMENT')
        self.assertEqual(len(result['records']),6)
        self.assertTrue(all(len(r['latency_seconds'])==24 for r in result['records']))
