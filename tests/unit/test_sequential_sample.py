import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cc_contract.cli import canonical
from cc_contract.contracts import UnsupportedScenario
from cc_contract.generators import generate
from cc_contract.model import execute
from cc_contract.native import InfrastructureFailure
from cc_contract.runner import ModelExecutor
from cc_contract.search import METHODS, schedule


ROOT = Path(__file__).resolve().parents[2]
LOADER = importlib.util.spec_from_file_location('sequential_sample', ROOT / 'scripts/run-sequential-sample.py')
sample = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(sample)


class SequentialSampleTests(unittest.TestCase):
    def test_development_schedule_preserves_reserved_schedule_and_seeds(self):
        reserved = schedule()
        jobs = sample.sample_schedule()
        self.assertEqual(len(jobs), 14)
        self.assertFalse({j['seed'] for j in jobs} & {j['seed'] for j in reserved})
        self.assertEqual(schedule(), reserved)
        self.assertEqual(len(reserved), 140)
        for block in range(2):
            group = [j for j in jobs if j['sample_block'] == block]
            self.assertEqual({j['method'] for j in group}, set(METHODS))
            self.assertEqual({j['budget_seconds'] for j in group}, {60})
            self.assertEqual({j['block'] for j in group}, {None})
            self.assertEqual({j['partition'] for j in group}, {sample.PARTITION})
            self.assertEqual(len({j['seed'] for j in group}), 1)
        self.assertEqual(jobs, sample.sample_schedule())

    def test_gpu_spec_binding_rejects_changes_before_backend_creation(self):
        spec = sample.make_spec('cuda')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'spec.json'
            for field, value in [('image_digest', 'mutable:latest'),
                                 ('harness_sha256', '0' * 64),
                                 ('source_commit', '0' * 40)]:
                changed = {**spec, field: value}
                payload = canonical(changed)
                path.write_bytes(payload)
                with self.subTest(field=field), patch.object(sample, 'backend') as factory, \
                        patch('sys.argv', ['sample', '--backend', 'cuda', '--spec', str(path),
                            '--spec-sha256', hashlib.sha256(payload).hexdigest(), '--output', str(Path(temporary) / 'out')]), \
                        patch('sys.stderr'):
                    with self.assertRaises(SystemExit) as exc:
                        sample.main()
                    self.assertEqual(exc.exception.code, 2)
                    factory.assert_not_called()
            with patch.dict('os.environ', {'CC_IMAGE_DIGEST': sample.IMAGE_DIGEST,
                                           'CC_COMMIT': sample.SOURCE_COMMIT}):
                payload = canonical(spec)
                checked = sample.validate_spec(payload, hashlib.sha256(payload).hexdigest(), 'cuda', 60)
                self.assertEqual(checked, spec)
                with self.assertRaisesRegex(ValueError, 'approved hash'):
                    sample.validate_spec(payload, '0' * 64, 'cuda', 60)
                reordered = copy.deepcopy(spec)
                reordered['schedule'].reverse()
                payload = canonical(reordered)
                with self.assertRaisesRegex(ValueError, 'predeclared'):
                    sample.validate_spec(payload, hashlib.sha256(payload).hexdigest(), 'cuda', 60)
            with patch.dict('os.environ', {'CC_IMAGE_DIGEST': 'bad', 'CC_COMMIT': sample.SOURCE_COMMIT}):
                payload = canonical(spec)
                with self.assertRaisesRegex(ValueError, 'immutable'):
                    sample.validate_spec(payload, hashlib.sha256(payload).hexdigest(), 'cuda', 60)
        with self.assertRaisesRegex(ValueError, 'exactly 60'):
            sample.make_spec('cuda', .05)

    def test_one_shared_executor_and_ordered_nonoverlapping_campaigns(self):
        case = generate(7, 'T01', size=2)
        calls, active, maximum, closed = [], [0], [0], [0]
        main_thread = threading.get_ident()
        class Worker(ModelExecutor):
            def execute(self, scenario):
                self_test.assertEqual(threading.get_ident(), main_thread)
                active[0] += 1
                maximum[0] = max(maximum[0], active[0])
                time.sleep(.001)
                try:
                    return execute(scenario)
                finally:
                    active[0] -= 1
            def close(self):
                closed[0] += 1
        self_test = self
        factory_calls = []
        def factory(name):
            factory_calls.append(name)
            return Worker()
        def campaign_fixture(worker, config, output):
            calls.append(config)
            worker.execute(case)
            run_id = 'campaign-fixture-' + str(len(calls))
            directory = output / run_id
            directory.mkdir()
            raw = canonical({'cpu_unit_fixture': True})
            (directory / 'records.jsonl').write_bytes(raw)
            manifest = {'run_id': run_id, 'state': 'COMPLETE_BUDGET', 'raw_file': 'records.jsonl',
                        'raw_sha256': hashlib.sha256(raw).hexdigest(), 'actual_seconds': .001,
                        'completed_cases': 1, 'candidate_draws': 1, 'counts': {'PASS': 1},
                        'coverage': {'structural': 1, 'temporal': 1}, 'configuration': config}
            (directory / 'start.json').write_bytes(canonical({'configuration': config, 'cpu_unit_fixture': True}))
            (directory / 'checkpoint.json').write_bytes(canonical({'cpu_unit_fixture': True}))
            (directory / 'manifest.json').write_bytes(canonical(manifest))
            return manifest
        spec = sample.make_spec('model', .05)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'out'
            receipt = sample.execute_sample(spec, canonical(spec), output, factory, campaign_fixture)
            self.assertEqual(receipt['state'], 'COMPLETE_SAMPLE')
            self.assertEqual(receipt['completed_jobs'], 14)
            self.assertEqual(calls, spec['schedule'])
            self.assertEqual(factory_calls, ['model'])
            self.assertEqual(maximum[0], 1)
            self.assertEqual(closed[0], 1)
            for before, after in zip(receipt['jobs'], receipt['jobs'][1:]):
                self.assertLessEqual(before['finished_monotonic_ns'], after['started_monotonic_ns'])
            self.assertFalse(receipt['gpu_executed'])
            self.assertFalse(receipt['confirmatory'])
            self.assertFalse(receipt['establishes_shorter_comparative_budget'])
            self.assertEqual(receipt['journal_sha256'], hashlib.sha256((output / 'journal.jsonl').read_bytes()).hexdigest())
            for job in receipt['jobs']:
                self.assertEqual(len(job['artifacts']), 4)
                for artifact in job['artifacts']:
                    raw = (output / artifact['file']).read_bytes()
                    self.assertEqual(artifact['bytes'], len(raw))
                    self.assertEqual(artifact['sha256'], hashlib.sha256(raw).hexdigest())

    def _single_case_policy(self):
        case = generate(9, 'T01', size=2)
        class FixedPolicy:
            def __init__(self, *_):
                import random
                self.draws, self.structural, self.temporal = 0, set(), set()
                self.rng = random.Random(7)
            def next(self):
                self.draws += 1
                return case
            def observe(self, _):
                self.structural.add('fixture')
        return FixedPolicy, case

    def test_candidate_and_unsupported_stop_after_preserving_original_record(self):
        policy, case = self._single_case_policy()
        for failure in ('FAIL', 'UNSUPPORTED', 'INFRA_FAILURE'):
            class Worker(ModelExecutor):
                def execute(self, scenario):
                    if failure == 'UNSUPPORTED':
                        raise UnsupportedScenario('controlled CPU unsupported fixture')
                    if failure == 'INFRA_FAILURE':
                        raise InfrastructureFailure('controlled CPU failure fixture')
                    result = execute(scenario)
                    result[0]['verdict'] = 'FAIL'
                    return result
            spec = sample.make_spec('model', .05)
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary, \
                    patch('cc_contract.runner.Search', policy):
                output = Path(temporary) / 'out'
                original_handler = signal.getsignal(signal.SIGTERM)
                receipt = sample.execute_sample(spec, canonical(spec), output, lambda _: Worker())
                self.assertEqual(signal.getsignal(signal.SIGTERM), original_handler)
                self.assertEqual(receipt['completed_jobs'], 1)
                self.assertNotEqual(receipt['state'], 'COMPLETE_SAMPLE')
                row = receipt['jobs'][0]
                raw = (output / row['raw_file']).read_bytes()
                records = [json.loads(line) for line in raw.splitlines()]
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]['scenario'], case)
                self.assertEqual(records[0]['verdict'], failure)
                self.assertEqual(row['raw_sha256'], hashlib.sha256(raw).hexdigest())
                if failure == 'FAIL':
                    self.assertEqual(receipt['state'], 'STOPPED_CANDIDATE_FAIL')
                    self.assertEqual(records[0]['observations'][0]['verdict'], 'FAIL')

    def test_trace_limit_retains_whole_case_and_stops_next_job(self):
        policy, case = self._single_case_policy()
        spec = sample.make_spec('model', .05)
        spec['trace_byte_limit_per_job'] = 1  # CPU guard fixture, never an approved GPU spec.
        original_serializer = sample.runner_module.canonical
        with tempfile.TemporaryDirectory() as temporary, patch('cc_contract.runner.Search', policy):
            output = Path(temporary) / 'out'
            receipt = sample.execute_sample(spec, canonical(spec), output, lambda _: ModelExecutor())
            self.assertEqual(receipt['state'], 'STOPPED_RESOURCE_LIMIT')
            self.assertEqual(receipt['completed_jobs'], 1)
            raw = (output / receipt['jobs'][0]['raw_file']).read_bytes()
            records = [json.loads(line) for line in raw.splitlines()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['scenario'], case)
            self.assertEqual(records[0]['verdict'], 'PASS')
            self.assertEqual(raw, canonical(records[0]))
            self.assertIs(sample.runner_module.canonical, original_serializer)

    def test_disk_reserve_blocks_backend_before_execution(self):
        spec = sample.make_spec('model', .05)
        with tempfile.TemporaryDirectory() as temporary, patch('shutil.disk_usage', return_value=SimpleNamespace(free=1)), \
                patch.object(sample, 'backend') as factory:
            output = Path(temporary) / 'out'
            receipt = sample.execute_sample(spec, canonical(spec), output)
            self.assertEqual(receipt['state'], 'STOPPED_RESOURCE_LIMIT')
            self.assertEqual(receipt['completed_jobs'], 0)
            factory.assert_not_called()
            self.assertTrue((output / 'receipt.json').is_file())

    def test_trace_limit_also_checks_rejected_cases_before_any_device_operation(self):
        case = generate(21, 'T01', size=2)
        del case['operations'][next(i for i, operation in enumerate(case['operations']) if operation['op'] == 'sync')]
        class InvalidPolicy:
            def __init__(self, *_):
                import random
                self.draws, self.structural, self.temporal = 0, set(), set()
                self.rng = random.Random(7)
            def next(self):
                self.draws += 1
                return case
        spec = sample.make_spec('model', .05)
        spec['trace_byte_limit_per_job'] = 1
        with tempfile.TemporaryDirectory() as temporary, patch('cc_contract.runner.Search', InvalidPolicy), \
                patch.object(ModelExecutor, 'execute') as device:
            output = Path(temporary) / 'out'
            receipt = sample.execute_sample(spec, canonical(spec), output, lambda _: ModelExecutor())
            self.assertEqual(receipt['state'], 'STOPPED_RESOURCE_LIMIT')
            self.assertEqual(receipt['completed_jobs'], 1)
            raw = (output / receipt['jobs'][0]['raw_file']).read_bytes()
            self.assertEqual(json.loads(raw)['verdict'], 'INVALID_TEST')
            self.assertEqual(json.loads(raw)['scenario'], case)
            device.assert_not_called()


if __name__ == '__main__':
    unittest.main()
