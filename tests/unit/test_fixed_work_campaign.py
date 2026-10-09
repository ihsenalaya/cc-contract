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
LOADER = importlib.util.spec_from_file_location('fixed_work_campaign', ROOT / 'scripts/run-fixed-work-campaign.py')
fixed = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(fixed)


class FixedWorkCampaignTests(unittest.TestCase):
    def setUp(self):
        self.provenance = patch('cc_contract.runner.provenance', return_value=('CPU_TEST_FIXTURE', False))
        self.provenance.start()
        self.addCleanup(self.provenance.stop)

    def spec(self, selected=4, guard=1):
        return fixed.make_spec('model', selected, guard, source_commit='CPU_TEST_FIXTURE')

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
        return FixedPolicy, legal

    def test_exact_reserved_order_seed_independence_and_old_files_unchanged(self):
        reserved_path = ROOT / fixed.RESERVED_SCHEDULE_FILE
        original = reserved_path.read_bytes()
        shared_original = (ROOT / 'scripts/run-work-sample.py').read_bytes()
        reserved = json.loads(original)
        jobs = fixed.campaign_schedule()
        self.assertEqual(len(jobs), 140)
        self.assertEqual(reserved, schedule())
        self.assertEqual([{key: job[key] for key in ('block', 'position', 'method', 'seed')}
                          for job in jobs],
                         [{key: job[key] for key in ('block', 'position', 'method', 'seed')}
                          for job in reserved])
        pilot_seeds = {job['seed'] for seed in (9100901, 9100902) for job in schedule(2, seed=seed)}
        self.assertFalse({job['seed'] for job in jobs} & pilot_seeds)
        for block in range(20):
            group = [job for job in jobs if job['block'] == block]
            self.assertEqual({job['method'] for job in group}, set(METHODS))
            self.assertEqual(len({job['seed'] for job in group}), 1)
            self.assertEqual({job['selected_case_target'] for job in group}, {100})
            self.assertEqual({job['budget_seconds'] for job in group}, {120})
        self.assertEqual(hashlib.sha256(reserved_path.read_bytes()).hexdigest(), fixed.RESERVED_SCHEDULE_SHA256)
        self.assertEqual(reserved_path.read_bytes(), original)
        self.assertEqual((ROOT / 'scripts/run-work-sample.py').read_bytes(), shared_original)

    def test_gpu_spec_strict_hash_protocol_helper_work_and_guard_bindings_before_backend(self):
        spec = fixed.make_spec('cuda')
        environment = {'CC_IMAGE_DIGEST': fixed.IMAGE_DIGEST, 'CC_COMMIT': fixed.SOURCE_COMMIT}
        with patch.dict('os.environ', environment):
            payload = canonical(spec)
            self.assertEqual(fixed.validate_spec(payload, hashlib.sha256(payload).hexdigest(), 'cuda'), spec)
            with self.assertRaisesRegex(ValueError, 'approved hash'):
                fixed.validate_spec(payload, '0' * 64, 'cuda')
        for count, guard in ((99, 120), (100, 119)):
            with self.assertRaisesRegex(ValueError, 'exactly 100'):
                fixed.make_spec('cuda', count, guard)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'spec.json'
            variations = []
            for field, value in [('protocol_sha256', '0' * 64), ('shared_harness_sha256', '0' * 64),
                                 ('harness_sha256', '0' * 64), ('selected_case_target', 99),
                                 ('image_digest', 'mutable:latest'), ('planned_jobs', 139),
                                 ('total_trace_byte_limit', 8 * 1024**3)]:
                variations.append({**spec, field: value})
            changed = copy.deepcopy(spec)
            changed['schedule'][0]['seed'] += 1
            variations.append(changed)
            variations.append({**spec, 'schedule': spec['schedule'][:-1]})
            for changed in variations:
                payload = canonical(changed)
                path.write_bytes(payload)
                with self.subTest(changed=next((k for k in spec if spec[k] != changed[k]), None)), \
                        patch.object(fixed, 'backend') as factory, patch('sys.stderr'), \
                        patch('sys.argv', ['campaign', '--backend', 'cuda', '--spec', str(path),
                              '--spec-sha256', hashlib.sha256(payload).hexdigest(),
                              '--output', str(Path(temporary) / 'out')]):
                    with self.assertRaises(SystemExit) as exc:
                        fixed.main()
                    self.assertEqual(exc.exception.code, 2)
                    factory.assert_not_called()
            helper = Path(temporary) / 'run-work-sample.py'
            helper.write_bytes(b'raise RuntimeError("must never execute")\n')
            with self.assertRaisesRegex(ValueError, 'immutable hash'):
                fixed.make_spec('model', helper_script=helper)
        with patch.dict('os.environ', {**environment, 'CC_COMMIT': 'wrong'}):
            with self.assertRaisesRegex(ValueError, 'source commit'):
                fixed.validate_spec(canonical(spec), hashlib.sha256(canonical(spec)).hexdigest(), 'cuda')

    def test_140_jobs_one_main_thread_executor_invalid_counts_and_original_bytes(self):
        policy, _ = self.policy(alternate_invalid=True)
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
        spec = self.spec()
        shared = fixed.load_shared_harness()
        original_canonical = shared.runner_module.canonical
        prior_signal = signal.getsignal(signal.SIGTERM)
        with tempfile.TemporaryDirectory() as temporary, patch('cc_contract.runner.Search', policy):
            output = Path(temporary) / 'runs'
            result = fixed.execute_campaign(spec, canonical(spec), output, factory)
            self.assertEqual(result['state'], fixed.COMPLETE_STATE)
            self.assertEqual(result['finite_work_completed_jobs'], 140)
            self.assertEqual(result['actual_selected_cases'], 560)
            self.assertEqual(result['execution_scope'], 'CPU_ORCHESTRATION_QUALIFICATION_ONLY')
            self.assertFalse(result['gpu_executed'])
            self.assertFalse(result['statistical_power_established'])
            self.assertFalse(result['establishes_statistical_superiority'])
            self.assertEqual(factories, ['model'])
            self.assertEqual(maximum[0], 1)
            self.assertEqual(closes[0], 1)
            self.assertEqual(calls[0], 280)  # Invalid quota entries are never executed.
            for index, job in enumerate(result['jobs']):
                self.assertEqual(job['configuration'], spec['schedule'][index])
                self.assertEqual(job['state'], 'COMPLETE_CASE_LIMIT_LOCAL_ONLY')
                self.assertTrue(job['fixed_work_completion'])
                self.assertAlmostEqual(job['job_wall_seconds'],
                    (job['finished_monotonic_ns'] - job['started_monotonic_ns']) / 1e9)
                self.assertGreaterEqual(job['job_wall_seconds'], job['diagnostics']['actual_seconds'])
                diagnostic = job['diagnostics']
                self.assertEqual(diagnostic['counts'], {'PASS': 2, 'INVALID_TEST': 2})
                self.assertEqual(diagnostic['valid_selected_fraction'], .5)
                self.assertEqual(diagnostic['candidate_draws'], 4)
                self.assertEqual([q['selected_cases'] for q in diagnostic['progress_quartiles']], [1, 2, 3, 4])
                raw = (output / job['raw_file']).read_bytes()
                self.assertEqual(raw, b''.join(canonical(json.loads(line)) for line in raw.splitlines()))
                self.assertEqual(job['raw_sha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(diagnostic['raw_trace_bytes'], len(raw))
                self.assertEqual(len(job['artifacts']), 4)
                for artifact in job['artifacts']:
                    data = (output / artifact['file']).read_bytes()
                    self.assertEqual(artifact['bytes'], len(data))
                    self.assertEqual(artifact['sha256'], hashlib.sha256(data).hexdigest())
            for before, after in zip(result['jobs'], result['jobs'][1:]):
                self.assertLessEqual(before['finished_monotonic_ns'], after['started_monotonic_ns'])
            self.assertEqual(result['actual_total_trace_bytes'],
                sum(job['diagnostics']['raw_trace_bytes'] for job in result['jobs']))
            self.assertEqual(result['journal_sha256'], hashlib.sha256((output / 'journal.jsonl').read_bytes()).hexdigest())
        self.assertEqual(signal.getsignal(signal.SIGTERM), prior_signal)
        self.assertIs(shared.runner_module.canonical, original_canonical)

    def test_deadline_at_full_quota_is_partial_and_no_next_job(self):
        policy, _ = self.policy()
        class SlowWorker(ModelExecutor):
            def execute(self, scenario):
                time.sleep(.01)
                return execute(scenario)
        spec = self.spec(selected=1, guard=.001)
        with tempfile.TemporaryDirectory() as temporary, patch('cc_contract.runner.Search', policy):
            result = fixed.execute_campaign(spec, canonical(spec), Path(temporary) / 'runs', lambda _: SlowWorker())
        self.assertEqual(result['state'], 'PARTIAL_SAFETY_TIMEOUT')
        self.assertEqual(result['completed_jobs'], 1)
        self.assertEqual(result['finite_work_completed_jobs'], 0)
        self.assertEqual(result['actual_selected_cases'], 1)
        self.assertEqual(result['jobs'][0]['state'], 'COMPLETE_BUDGET')
        self.assertFalse(result['jobs'][0]['fixed_work_completion'])

    def test_overall_guard_after_a_full_quota_remains_partial(self):
        policy, _ = self.policy()
        clock = [0]
        original_campaign = fixed.campaign
        def finish_after_overall_guard(*args, **kwargs):
            manifest = original_campaign(*args, **kwargs)
            clock[0] = 2_000_000_000
            return manifest
        with patch.object(fixed, 'OVERALL_COMMAND_TIMEOUT_SECONDS', 1), \
                patch.object(fixed.time, 'monotonic_ns', side_effect=lambda: clock[0]), \
                patch('cc_contract.runner.Search', policy), tempfile.TemporaryDirectory() as temporary:
            spec = self.spec(selected=1)
            result = fixed.execute_campaign(spec, canonical(spec), Path(temporary) / 'runs',
                                            campaign_function=finish_after_overall_guard)
        self.assertEqual(result['state'], 'PARTIAL_COMMAND_TIMEOUT')
        self.assertEqual(result['completed_jobs'], 1)
        self.assertEqual(result['actual_selected_cases'], 1)
        self.assertEqual(result['finite_work_completed_jobs'], 0)
        self.assertEqual(result['jobs'][0]['state'], 'COMPLETE_CASE_LIMIT_LOCAL_ONLY')
        self.assertFalse(result['jobs'][0]['fixed_work_completion'])

    def test_fail_unsupported_infra_stop_preserve_exact_original_candidate(self):
        policy, legal = self.policy()
        spec = self.spec()
        for failure in ('FAIL', 'UNSUPPORTED', 'INFRA_FAILURE'):
            class Worker(ModelExecutor):
                def execute(self, scenario):
                    if failure == 'UNSUPPORTED':
                        raise UnsupportedScenario('controlled CPU unsupported fixture')
                    if failure == 'INFRA_FAILURE':
                        raise InfrastructureFailure('controlled CPU infrastructure fixture')
                    observations = execute(scenario)
                    observations[0]['verdict'] = 'FAIL'
                    return observations
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary, \
                    patch('cc_contract.runner.Search', policy):
                output = Path(temporary) / 'runs'
                result = fixed.execute_campaign(spec, canonical(spec), output, lambda _: Worker())
                self.assertTrue(result['state'].startswith('PARTIAL_'))
                self.assertEqual(result['completed_jobs'], 1)
                self.assertEqual(result['finite_work_completed_jobs'], 0)
                row = json.loads((output / result['jobs'][0]['raw_file']).read_bytes())
                self.assertEqual(row['scenario'], legal)
                self.assertEqual(row['verdict'], failure)
                self.assertFalse(row['confirmed_distinct_defect'])
                self.assertFalse(result['jobs'][0]['fixed_work_completion'])

    def test_resource_guards_stop_at_whole_record_without_completing_last_quota(self):
        policy, _ = self.policy()
        for constant in ('TRACE_BYTE_LIMIT_PER_JOB', 'TOTAL_TRACE_BYTE_LIMIT'):
            with self.subTest(constant=constant), patch.object(fixed, constant, 1), \
                    tempfile.TemporaryDirectory() as temporary, patch('cc_contract.runner.Search', policy):
                spec = self.spec(selected=1)
                output = Path(temporary) / 'runs'
                result = fixed.execute_campaign(spec, canonical(spec), output)
                self.assertEqual(result['state'], 'PARTIAL_RESOURCE_LIMIT')
                self.assertEqual(result['completed_jobs'], 1)
                self.assertEqual(result['finite_work_completed_jobs'], 0)
                raw = (output / result['jobs'][0]['raw_file']).read_bytes()
                self.assertEqual(raw, canonical(json.loads(raw)))
        with tempfile.TemporaryDirectory() as temporary, \
                patch('shutil.disk_usage', return_value=SimpleNamespace(free=1)), \
                patch.object(fixed, 'backend') as factory:
            spec = self.spec()
            result = fixed.execute_campaign(spec, canonical(spec), Path(temporary) / 'runs')
            self.assertEqual(result['state'], 'PARTIAL_RESOURCE_LIMIT')
            self.assertEqual(result['completed_jobs'], 0)
            factory.assert_not_called()

    def test_global_guard_includes_previous_job_bytes(self):
        policy, _ = self.policy()
        with patch.object(fixed, 'TOTAL_TRACE_BYTE_LIMIT', 2100), tempfile.TemporaryDirectory() as temporary, \
                patch('cc_contract.runner.Search', policy):
            spec = self.spec(selected=1)
            result = fixed.execute_campaign(spec, canonical(spec), Path(temporary) / 'runs')
            self.assertEqual(result['state'], 'PARTIAL_RESOURCE_LIMIT')
            self.assertEqual(result['completed_jobs'], 2)
            self.assertEqual(result['finite_work_completed_jobs'], 1)
            self.assertTrue(result['jobs'][0]['fixed_work_completion'])
            self.assertFalse(result['jobs'][1]['fixed_work_completion'])
            self.assertGreaterEqual(result['actual_total_trace_bytes'], 2100)

    def test_changed_object_or_non_main_thread_rejected_before_backend(self):
        spec = self.spec()
        changed = {**spec, 'selected_case_target': 3}
        with tempfile.TemporaryDirectory() as temporary, patch.object(fixed, 'backend') as factory:
            with self.assertRaisesRegex(ValueError, 'differs from'):
                fixed.execute_campaign(changed, canonical(spec), Path(temporary) / 'runs')
            factory.assert_not_called()
        errors = []
        def call():
            try:
                fixed.execute_campaign(spec, canonical(spec), Path('/does-not-exist'))
            except ValueError as error:
                errors.append(str(error))
        thread = threading.Thread(target=call)
        thread.start()
        thread.join()
        self.assertEqual(errors, ['Campaign must run on the main thread for durable signal handling'])


if __name__ == '__main__':
    unittest.main()
