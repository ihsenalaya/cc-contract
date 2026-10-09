import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import random
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
LOADER = importlib.util.spec_from_file_location('work_sample', ROOT / 'scripts/run-work-sample.py')
sample = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(sample)


class WorkSampleTests(unittest.TestCase):
    def policy(self, alternate_invalid=False):
        legal = generate(9, 'T01', size=2)
        invalid = copy.deepcopy(legal)
        del invalid['operations'][next(i for i, op in enumerate(invalid['operations']) if op['op'] == 'sync')]
        class FixedPolicy:
            def __init__(self, *_):
                self.draws, self.structural, self.temporal = 0, set(), set()
                self.rng = random.Random(7)
            def next(self):
                self.draws += 1
                return invalid if alternate_invalid and self.draws % 2 == 0 else legal
            def observe(self, _):
                self.structural.add('fixture')
                self.temporal.add('fixture')
        return FixedPolicy, legal, invalid

    def test_new_schedule_disjoint_and_reserved_unchanged(self):
        before = schedule()
        jobs = sample.sample_schedule()
        excluded = before + schedule(2, seed=9100901)
        self.assertEqual(len(jobs), 14)
        self.assertFalse({j['seed'] for j in jobs} & {j['seed'] for j in excluded})
        self.assertEqual(schedule(), before)
        for block in range(2):
            group = [j for j in jobs if j['sample_block'] == block]
            self.assertEqual({j['method'] for j in group}, set(METHODS))
            self.assertEqual({j['selected_case_target'] for j in group}, {100})
            self.assertEqual({j['max_cases'] for j in group}, {100})
            self.assertEqual({j['budget_seconds'] for j in group}, {120})
            self.assertEqual({j['partition'] for j in group}, {sample.PARTITION})
            self.assertEqual({j['block'] for j in group}, {None})
        self.assertEqual(jobs, sample.sample_schedule())

    def test_spec_binding_rejects_changed_work_or_guard_before_backend(self):
        spec = sample.make_spec('cuda')
        with patch.dict('os.environ', {'CC_IMAGE_DIGEST': sample.IMAGE_DIGEST,
                                       'CC_COMMIT': sample.SOURCE_COMMIT}):
            payload = canonical(spec)
            self.assertEqual(sample.validate_spec(payload, hashlib.sha256(payload).hexdigest(), 'cuda'), spec)
            with self.assertRaisesRegex(ValueError, 'approved hash'):
                sample.validate_spec(payload, '0' * 64, 'cuda')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'spec.json'
            for field, value in [('selected_case_target', 99), ('image_digest', 'mutable:latest'),
                                 ('harness_sha256', '0' * 64), ('safety_timeout_seconds', 121),
                                 ('total_trace_byte_limit', 99999999999)]:
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
        for count, guard in ((99, 120), (100, 119)):
            with self.assertRaisesRegex(ValueError, 'exactly 100'):
                sample.make_spec('cuda', count, guard)

    def test_fixed_selected_work_includes_invalid_and_uses_one_executor(self):
        policy, legal, invalid = self.policy(alternate_invalid=True)
        active, maximum, calls, closes, factories = [0], [0], [0], [0], []
        main_thread = threading.get_ident()
        test = self
        class Worker(ModelExecutor):
            def execute(self, scenario):
                test.assertEqual(threading.get_ident(), main_thread)
                active[0] += 1
                maximum[0] = max(maximum[0], active[0])
                calls[0] += 1
                try:
                    return execute(scenario)
                finally:
                    active[0] -= 1
            def close(self):
                closes[0] += 1
        def factory(name):
            factories.append(name)
            return Worker()
        spec = sample.make_spec('model', 4, 1)
        original_canonical = sample.runner_module.canonical
        with tempfile.TemporaryDirectory() as temporary, patch('cc_contract.runner.Search', policy):
            output = Path(temporary) / 'runs'
            result = sample.execute_sample(spec, canonical(spec), output, factory)
            self.assertEqual(result['state'], 'COMPLETE_FINITE_WORK_SAMPLE')
            self.assertEqual(result['finite_work_completed_jobs'], 14)
            self.assertEqual(result['completed_jobs'], 14)
            self.assertEqual(factories, ['model'])
            self.assertEqual(maximum[0], 1)
            self.assertEqual(closes[0], 1)
            self.assertEqual(calls[0], 28)  # Invalid selected cases never reached the executor.
            self.assertFalse(result['gpu_executed'])
            self.assertFalse(result['establishes_shorter_comparative_budget'])
            for index, job in enumerate(result['jobs']):
                self.assertEqual(job['configuration'], spec['schedule'][index])
                self.assertEqual(job['state'], 'COMPLETE_CASE_LIMIT_LOCAL_ONLY')
                self.assertTrue(job['development_finite_work_completion'])
                diagnostic = job['diagnostics']
                self.assertEqual(diagnostic['completed_cases'], 4)
                self.assertEqual(diagnostic['counts'], {'PASS': 2, 'INVALID_TEST': 2})
                self.assertEqual(diagnostic['candidate_draws'], 4)
                self.assertEqual([q['selected_cases'] for q in diagnostic['progress_quartiles']], [1, 2, 3, 4])
                self.assertLess(diagnostic['actual_seconds'], 1)
                self.assertEqual(diagnostic['observations'], 2)
                self.assertEqual(diagnostic['observed_integer_payload_bytes'], 16)
                raw = (output / job['raw_file']).read_bytes()
                self.assertEqual(diagnostic['raw_trace_bytes'], len(raw))
                rows = [json.loads(line) for line in raw.splitlines()]
                self.assertEqual(raw, b''.join(canonical(row) for row in rows))
                checkpoint = json.loads((output / job['run_id'] / 'checkpoint.json').read_bytes())
                self.assertEqual(diagnostic['progress_quartiles'][-1]['checkpoint_elapsed_seconds_after_case_fsync'], checkpoint['elapsed_seconds'])
                self.assertEqual(job['raw_sha256'], hashlib.sha256(raw).hexdigest())
                for artifact in job['artifacts']:
                    payload = (output / artifact['file']).read_bytes()
                    self.assertEqual(artifact['bytes'], len(payload))
                    self.assertEqual(artifact['sha256'], hashlib.sha256(payload).hexdigest())
            for previous, current in zip(result['jobs'], result['jobs'][1:]):
                self.assertLessEqual(previous['finished_monotonic_ns'], current['started_monotonic_ns'])
            self.assertEqual(result['actual_total_trace_bytes'], sum(j['diagnostics']['raw_trace_bytes'] for j in result['jobs']))
            self.assertEqual(result['journal_sha256'], hashlib.sha256((output / 'journal.jsonl').read_bytes()).hexdigest())
            self.assertIs(sample.runner_module.canonical, original_canonical)

    def test_safety_deadline_produces_partial_and_stops_following_jobs(self):
        policy, _, _ = self.policy()
        class SlowWorker(ModelExecutor):
            def execute(self, scenario):
                time.sleep(.01)
                return execute(scenario)
        spec = sample.make_spec('model', 4, .001)
        with tempfile.TemporaryDirectory() as temporary, patch('cc_contract.runner.Search', policy):
            output = Path(temporary) / 'runs'
            result = sample.execute_sample(spec, canonical(spec), output, lambda _: SlowWorker())
            self.assertEqual(result['state'], 'STOPPED_SAFETY_TIMEOUT')
            self.assertEqual(result['completed_jobs'], 1)
            self.assertEqual(result['finite_work_completed_jobs'], 0)
            self.assertEqual(result['jobs'][0]['state'], 'COMPLETE_BUDGET')
            self.assertEqual(result['jobs'][0]['diagnostics']['completed_cases'], 1)
            self.assertFalse(result['jobs'][0]['development_finite_work_completion'])

    def test_candidate_unsupported_and_infra_preserve_original_record(self):
        policy, legal, _ = self.policy()
        spec = sample.make_spec('model', 4, 1)
        for failure in ('FAIL', 'UNSUPPORTED', 'INFRA_FAILURE'):
            class Worker(ModelExecutor):
                def execute(self, scenario):
                    if failure == 'UNSUPPORTED':
                        raise UnsupportedScenario('controlled CPU unsupported fixture')
                    if failure == 'INFRA_FAILURE':
                        raise InfrastructureFailure('controlled CPU failure fixture')
                    rows = execute(scenario)
                    rows[0]['verdict'] = 'FAIL'
                    return rows
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary, \
                    patch('cc_contract.runner.Search', policy):
                output = Path(temporary) / 'runs'
                prior_signal = signal.getsignal(signal.SIGTERM)
                result = sample.execute_sample(spec, canonical(spec), output, lambda _: Worker())
                self.assertEqual(signal.getsignal(signal.SIGTERM), prior_signal)
                self.assertEqual(result['completed_jobs'], 1)
                self.assertEqual(result['finite_work_completed_jobs'], 0)
                row = json.loads((output / result['jobs'][0]['raw_file']).read_bytes())
                self.assertEqual(row['scenario'], legal)
                self.assertEqual(row['verdict'], failure)
                self.assertFalse(result['jobs'][0]['development_finite_work_completion'])
                if failure == 'FAIL':
                    self.assertEqual(result['state'], 'STOPPED_CANDIDATE_FAIL')

    def test_job_and_global_trace_caps_preserve_complete_record_and_never_complete(self):
        policy, _, _ = self.policy()
        for limit in ('trace_byte_limit_per_job', 'total_trace_byte_limit'):
            spec = sample.make_spec('model', 1, 1)
            spec[limit] = 1  # Guard fixture, not an approved GPU specification.
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as temporary, \
                    patch('cc_contract.runner.Search', policy):
                output = Path(temporary) / 'runs'
                result = sample.execute_sample(spec, canonical(spec), output, lambda _: ModelExecutor())
                self.assertEqual(result['state'], 'STOPPED_RESOURCE_LIMIT')
                self.assertEqual(result['completed_jobs'], 1)
                self.assertEqual(result['finite_work_completed_jobs'], 0)
                self.assertFalse(result['jobs'][0]['development_finite_work_completion'])
                raw = (output / result['jobs'][0]['raw_file']).read_bytes()
                self.assertEqual(len(raw.splitlines()), 1)
                self.assertEqual(raw, canonical(json.loads(raw)))

    def test_disk_reserve_stops_before_backend_creation(self):
        spec = sample.make_spec('model', 4, 1)
        with tempfile.TemporaryDirectory() as temporary, \
                patch('shutil.disk_usage', return_value=SimpleNamespace(free=1)), \
                patch.object(sample, 'backend') as factory:
            output = Path(temporary) / 'runs'
            result = sample.execute_sample(spec, canonical(spec), output)
            self.assertEqual(result['state'], 'STOPPED_RESOURCE_LIMIT')
            self.assertEqual(result['completed_jobs'], 0)
            factory.assert_not_called()
            self.assertTrue((output / 'receipt.json').is_file())

    def test_global_limit_counts_prior_job_originals(self):
        policy, _, _ = self.policy()
        spec = sample.make_spec('model', 1, 1)
        # First record fits individually; accumulated second record crosses cap.
        spec['total_trace_byte_limit'] = 2100
        with tempfile.TemporaryDirectory() as temporary, patch('cc_contract.runner.Search', policy):
            output = Path(temporary) / 'runs'
            result = sample.execute_sample(spec, canonical(spec), output, lambda _: ModelExecutor())
            self.assertEqual(result['state'], 'STOPPED_RESOURCE_LIMIT')
            self.assertEqual(result['completed_jobs'], 2)
            self.assertEqual(result['finite_work_completed_jobs'], 1)
            self.assertTrue(result['jobs'][0]['development_finite_work_completion'])
            self.assertFalse(result['jobs'][1]['development_finite_work_completion'])
            self.assertGreaterEqual(result['actual_total_trace_bytes'], 2100)


if __name__ == '__main__':
    unittest.main()
