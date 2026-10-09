#!/usr/bin/env python3
"""Finite-work development timing pilot; fixed selected cases, one at a time.

This diagnostic never changes the reserved E4/E5 schedule or establishes
statistical superiority, absolute hardware correctness, or a shorter budget.
GPU host/96-case qualification is an external prerequisite, not repeated here.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

from cc_contract.cli import canonical, provenance
from cc_contract.contracts import UnsupportedScenario
from cc_contract.native import InfrastructureFailure
from cc_contract.runner import backend, campaign, utc
import cc_contract.runner as runner_module
from cc_contract.search import METHODS, schedule


IMAGE_DIGEST = 'ghcr.io/ihsenalaya/cc-contract-ir@sha256:e09597869dab698d082cc56ceb5cbb7c6eb348760e08f617387491837ad1fc8a'
SOURCE_COMMIT = '1f62b1838196e495d715c1cf063b03ea777aaa94'
SCHEDULE_SEED = 9100902
PARTITION = 'development_finite_work_time_pilot'
EXPERIMENT = 'FINITE_WORK_TIME_DEVELOPMENT_PILOT'
SELECTED_CASE_TARGET = 100
SAFETY_TIMEOUT_SECONDS = 120
PROJECTION_TARGETS = (100, 1000, 10000)
COMPLETION_RULE = 'FIXED_SELECTED_CASES_INCLUDING_INVALID_TEST'


def harness_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def sample_schedule(selected_case_target=SELECTED_CASE_TARGET,
                    safety_timeout_seconds=SAFETY_TIMEOUT_SECONDS):
    """Predeclared, randomized order, independent of reserved evaluation seeds."""
    jobs = schedule(blocks=2, budget_seconds=safety_timeout_seconds, seed=SCHEDULE_SEED)
    excluded = schedule() + schedule(blocks=2, seed=9100901)
    if {j['seed'] for j in jobs} & {j['seed'] for j in excluded}:
        raise ValueError('Development, prior-pilot and reserved campaign seeds overlap')
    return [{**job, 'block': None, 'sample_block': job['block'],
             'partition': PARTITION, 'max_cases': selected_case_target,
             'selected_case_target': selected_case_target,
             'completion_rule': COMPLETION_RULE, 'confirmatory': False} for job in jobs]


def make_spec(backend_name, selected_case_target=SELECTED_CASE_TARGET,
              safety_timeout_seconds=SAFETY_TIMEOUT_SECONDS, source_commit=None):
    if backend_name not in ('model', 'native-reference', 'cuda'):
        raise ValueError('Unsupported backend')
    if (type(selected_case_target) is not int or selected_case_target < 1 or
            selected_case_target > SELECTED_CASE_TARGET):
        raise ValueError('Selected case count must be an integer from 1 to 100')
    if (type(safety_timeout_seconds) not in (int, float) or
            not 0 < safety_timeout_seconds <= SAFETY_TIMEOUT_SECONDS):
        raise ValueError('Safety timeout must be positive and at most 120 seconds')
    if backend_name == 'cuda' and (selected_case_target != SELECTED_CASE_TARGET or
            safety_timeout_seconds != SAFETY_TIMEOUT_SECONDS):
        raise ValueError('Approved GPU sample requires exactly 100 selected cases and a 120-second guard')
    return {'schema_version': 2, 'experiment': EXPERIMENT, 'backend': backend_name,
            'image_digest': IMAGE_DIGEST if backend_name == 'cuda' else
                os.environ.get('CC_IMAGE_DIGEST', 'NOT_APPLICABLE_LOCAL_PROCESS'),
            'source_commit': SOURCE_COMMIT if backend_name == 'cuda' else
                (source_commit or provenance()[0]),
            'harness_sha256': harness_sha256(), 'schedule_seed': SCHEDULE_SEED,
            'schedule': sample_schedule(selected_case_target, safety_timeout_seconds),
            'selected_case_target': selected_case_target,
            'safety_timeout_seconds': safety_timeout_seconds,
            'completion_rule': COMPLETION_RULE,
            'projection_targets': list(PROJECTION_TARGETS), 'confirmatory': False,
            'comparison_schedule_changed': False,
            'trace_byte_limit_per_job': 1073741824,
            'total_trace_byte_limit': 8589934592,
            'minimum_free_bytes': 2147483648,
            'oracle_version': 'integer_physical_tag_v2'}


def validate_spec(spec_bytes, expected_sha256, backend_name,
                  selected_case_target=SELECTED_CASE_TARGET,
                  safety_timeout_seconds=SAFETY_TIMEOUT_SECONDS):
    if expected_sha256 != hashlib.sha256(spec_bytes).hexdigest():
        raise ValueError('Sample spec hash differs from the approved hash')
    spec = json.loads(spec_bytes)
    expected = make_spec(backend_name, selected_case_target, safety_timeout_seconds,
                         spec.get('source_commit'))
    if spec != expected:
        raise ValueError('Sample spec configuration or harness differs from predeclared sample')
    if backend_name == 'cuda':
        if os.environ.get('CC_IMAGE_DIGEST') != IMAGE_DIGEST:
            raise ValueError('GPU sample requires the pinned immutable IR image digest')
        if os.environ.get('CC_COMMIT') != SOURCE_COMMIT:
            raise ValueError('GPU sample requires the pinned IR source commit')
    return spec


def write_original(path, payload):
    with path.open('xb') as target:
        target.write(payload)
        target.flush()
        os.fsync(target.fileno())
    path.chmod(0o444)


class StopAfterCandidate:
    """Let campaign persist its original FAIL/UNSUPPORTED before stopping.

    campaign's main-thread signal handler turns SIGTERM into a request to stop
    at the next loop boundary. It therefore retains the observations and reason
    rather than replacing a candidate with a synthetic infrastructure failure.
    """
    def __init__(self, executor):
        self.executor = executor
        self.environment = executor.environment
        self.capabilities = executor.capabilities
        self.stop_reason = None

    def stop(self, reason):
        if self.stop_reason is not None:
            return
        self.stop_reason = reason
        if not callable(signal.getsignal(signal.SIGTERM)):
            raise InfrastructureFailure('Candidate stop requested outside campaign handler')
        signal.raise_signal(signal.SIGTERM)

    def execute(self, scenario):
        if self.stop_reason is not None:
            raise InfrastructureFailure('Execution requested after candidate stop')
        try:
            result = self.executor.execute(scenario)
        except UnsupportedScenario:
            self.stop('UNSUPPORTED')
            raise
        if any(observation['verdict'] == 'FAIL' for observation in result):
            self.stop('CANDIDATE_FAIL')
        return result


class ResourceLimit(InfrastructureFailure):
    pass


def resource_limit_reason(output, spec, run_id=None, pending_bytes=0,
                          previous_trace_bytes=0):
    import shutil
    if shutil.disk_usage(output).free - pending_bytes < spec['minimum_free_bytes']:
        return 'Disk free space would fall below the predeclared reserve'
    if run_id is not None:
        raw = output / run_id / 'records.jsonl'
        if raw.stat().st_size + pending_bytes >= spec['trace_byte_limit_per_job']:
            return 'Original case trace reached the predeclared byte limit'
        if previous_trace_bytes + raw.stat().st_size + pending_bytes >= spec['total_trace_byte_limit']:
            return 'Total original case traces reached the predeclared byte limit'
    elif previous_trace_bytes >= spec['total_trace_byte_limit']:
        return 'Total original case traces reached the predeclared byte limit'
    return None


class CaseDiagnostics:
    """Small streaming counters; original case bytes are never rewritten."""
    def __init__(self, selected_case_target):
        self.target = selected_case_target
        self.thresholds = {max(1, (selected_case_target * q + 3) // 4)
                           for q in (1, 2, 3, 4)}
        self.counts = Counter()
        self.raw_trace_bytes = self.observations = self.observed_integer_payload_bytes = 0
        self.last_case_elapsed = None
        self.progress_quartiles = []

    def case(self, value, payload):
        self.counts[value['verdict']] += 1
        self.raw_trace_bytes += len(payload)
        self.observations += len(value['observations'])
        self.observed_integer_payload_bytes += 4 * sum(
            len(observation['observed']['values']) for observation in value['observations'])
        self.last_case_elapsed = value['elapsed_seconds']

    def checkpoint(self, value):
        count = value['completed_cases']
        if count in self.thresholds:
            self.progress_quartiles.append({
                'selected_cases': count, 'candidate_draws': value['draws'],
                'coverage': {'structural': len(value['structural']),
                             'temporal': len(value['temporal'])},
                'counts': dict(self.counts),
                'elapsed_seconds_before_serialization_and_fsync': self.last_case_elapsed,
                'checkpoint_elapsed_seconds_after_case_fsync': value['elapsed_seconds'],
                'raw_trace_bytes': self.raw_trace_bytes, 'observations': self.observations,
                'observed_integer_payload_bytes': self.observed_integer_payload_bytes,
                'time_basis': 'case_elapsed_before_serialization_and_fsync'})


@contextmanager
def guarded_case_records(monitored, output, spec, diagnostics, previous_trace_bytes):
    """Observe every record, including INVALID_TEST, without changing its bytes.

    The existing runner has no case callback. Its serialization function is
    temporarily wrapped only while a single main-thread campaign is active.
    The record that crosses a limit is written whole; overshoot is bounded by
    one record. Signals request the existing durable loop-boundary stop.
    """
    original = runner_module.canonical
    def serialize(value):
        payload = original(value)
        if isinstance(value, dict) and value.get('record_type') == 'case':
            diagnostics.case(value, payload)
            reason = resource_limit_reason(output, spec, value['run_id'], len(payload),
                                           previous_trace_bytes)
            if reason:
                monitored.stop('RESOURCE_LIMIT')
        elif isinstance(value, dict) and 'next_action_on_failure' in value:
            diagnostics.checkpoint(value)
        return payload
    runner_module.canonical = serialize
    try:
        yield
    finally:
        runner_module.canonical = original


def job_diagnostics(manifest, diagnostics):
    counts = manifest['counts']
    seconds = manifest['actual_seconds']
    cases = manifest['completed_cases']
    return {'completed_cases': cases, 'counts': counts,
            'candidate_draws': manifest['candidate_draws'],
            'actual_seconds': seconds, 'coverage': manifest['coverage'],
            'cases_per_second': cases / seconds if seconds > 0 else None,
            'passing_cases_per_second': counts.get('PASS', 0) / seconds if seconds > 0 else None,
            'candidate_draws_per_second': manifest['candidate_draws'] / seconds if seconds > 0 else None,
            'invalid_fraction': counts.get('INVALID_TEST', 0) / cases if cases else None,
            'seconds_per_selected_case': seconds / cases if cases else None,
            'observations': diagnostics.observations,
            'seconds_per_observation': seconds / diagnostics.observations if diagnostics.observations else None,
            'observed_integer_payload_bytes': diagnostics.observed_integer_payload_bytes,
            'observed_payload_bytes_scope': 'SUM_OF_OBSERVED_INT32_VALUES_NOT_PHYSICAL_BUS_TRAFFIC',
            'raw_trace_bytes': diagnostics.raw_trace_bytes,
            'trace_bytes_per_selected_case': diagnostics.raw_trace_bytes / cases if cases else None,
            'progress_quartiles': diagnostics.progress_quartiles,
            'confirmed_defects': [], 'diagnostic_only': True}


def original_artifacts(output, manifest, config):
    run_id = manifest['run_id']
    if Path(run_id).name != run_id or not run_id.startswith('campaign-'):
        raise InfrastructureFailure('Campaign returned an unsafe run identifier')
    if manifest['configuration'] != config:
        raise InfrastructureFailure('Campaign configuration differs from predeclared job')
    directory = output / run_id
    artifacts = []
    for name in ('start.json', 'records.jsonl', 'checkpoint.json', 'manifest.json'):
        path = directory / name
        if name == 'checkpoint.json' and manifest['completed_cases'] == 0 and not path.exists():
            continue
        if not path.is_file() or path.is_symlink():
            raise InfrastructureFailure('Campaign original artifact missing or unsafe: ' + name)
        digest = hashlib.sha256()
        size = 0
        with path.open('rb') as source:
            while chunk := source.read(8 * 1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        artifacts.append({'file': run_id + '/' + name, 'bytes': size, 'sha256': digest.hexdigest()})
    raw_artifact = next(artifact for artifact in artifacts if artifact['file'].endswith('/records.jsonl'))
    if manifest['raw_file'] != 'records.jsonl' or raw_artifact['sha256'] != manifest['raw_sha256']:
        raise InfrastructureFailure('Campaign original case trace hash differs from manifest')
    return artifacts


def execute_sample(spec, spec_bytes, output, executor_factory=None, campaign_function=None):
    if threading.current_thread() is not threading.main_thread():
        raise ValueError('Sample must run on the main thread for durable campaign signal handling')
    executor_factory = executor_factory or backend
    campaign_function = campaign_function or campaign
    started_utc, started_ns = utc(), time.monotonic_ns()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    write_original(output / 'spec.json', spec_bytes)
    jobs, executor, monitored = [], None, None
    previous_trace_bytes = 0
    state, error, environment = 'INFRA_FAILURE', None, None
    initialization_seconds, close_seconds = None, None
    interrupted = {'value': False}
    previous = {sig: signal.signal(sig, lambda *_: interrupted.update(value=True))
                for sig in (signal.SIGINT, signal.SIGTERM)}
    journal_path = output / 'journal.jsonl'
    with journal_path.open('xb') as journal:
        def event(kind, **details):
            journal.write(canonical({'event': kind, 'timestamp_utc': utc(),
                                     'monotonic_ns': time.monotonic_ns(), **details}))
            journal.flush()
            os.fsync(journal.fileno())

        event('sample_start', planned_jobs=len(spec['schedule']), confirmatory=False)
        try:
            reason = resource_limit_reason(output, spec)
            if reason:
                raise ResourceLimit(reason)
            initialization_started = time.monotonic_ns()
            executor = executor_factory(spec['backend'])
            initialization_seconds = (time.monotonic_ns() - initialization_started) / 1e9
            environment = executor.environment
            if spec['backend'] == 'cuda':
                if environment.get('gpu_executed') is not True or not all(
                        executor.capabilities.get(feature) is True for feature in ('mapped', 'graphs')):
                    raise InfrastructureFailure('GPU sample requires externally qualified CUDA T01-T08 support')
            elif environment.get('gpu_executed') is not False:
                raise InfrastructureFailure('CPU sample executor unexpectedly reports GPU execution')
            monitored = StopAfterCandidate(executor)
            event('backend_ready', environment=environment, capabilities=executor.capabilities)
            state = 'COMPLETE_FINITE_WORK_SAMPLE'
            for index, config in enumerate(spec['schedule']):
                if interrupted['value']:
                    state = 'STOPPED_INTERRUPTED'
                    break
                reason = resource_limit_reason(output, spec,
                                               previous_trace_bytes=previous_trace_bytes)
                if reason:
                    raise ResourceLimit(reason)
                begin_utc, begin_ns = utc(), time.monotonic_ns()
                event('job_start', job_index=index, configuration=config)
                diagnostics = CaseDiagnostics(config['selected_case_target'])
                with guarded_case_records(monitored, output, spec, diagnostics,
                                          previous_trace_bytes):
                    manifest = campaign_function(monitored, config, output,
                                                 max_cases=config['max_cases'])
                artifacts = original_artifacts(output, manifest, config)
                raw_artifact = next(item for item in artifacts
                                    if item['file'].endswith('/records.jsonl'))
                if (dict(diagnostics.counts) != manifest['counts'] or
                        sum(diagnostics.counts.values()) != manifest['completed_cases'] or
                        diagnostics.raw_trace_bytes != raw_artifact['bytes']):
                    raise InfrastructureFailure('Streaming original-case diagnostics disagree with manifest')
                finish_ns, finish_utc = time.monotonic_ns(), utc()
                if jobs and begin_ns < jobs[-1]['finished_monotonic_ns']:
                    raise InfrastructureFailure('Sequential job timestamps overlap')
                finite_complete = (
                    manifest['state'] == 'COMPLETE_CASE_LIMIT_LOCAL_ONLY' and
                    manifest['completed_cases'] == config['selected_case_target'] and
                    not monitored.stop_reason and manifest.get('error') is None and
                    not any(manifest['counts'].get(v, 0)
                            for v in ('FAIL', 'UNSUPPORTED', 'INFRA_FAILURE')))
                entry = {'job_index': index, 'configuration': config,
                         'started_utc': begin_utc, 'finished_utc': finish_utc,
                         'started_monotonic_ns': begin_ns, 'finished_monotonic_ns': finish_ns,
                         'run_id': manifest['run_id'], 'state': manifest['state'],
                         'manifest_file': manifest['run_id'] + '/manifest.json',
                         'raw_file': manifest['run_id'] + '/' + manifest['raw_file'],
                         'raw_sha256': manifest['raw_sha256'],
                         'artifacts': artifacts,
                         'development_finite_work_completion': finite_complete,
                         'original_state_scope': 'LEGACY_CASE_LIMIT_LABEL_PRESERVED_DEVELOPMENT_PILOT_ONLY',
                         'diagnostics': job_diagnostics(manifest, diagnostics)}
                jobs.append(entry)
                previous_trace_bytes += diagnostics.raw_trace_bytes
                event('job_finish', **entry)
                counts = manifest['counts']
                if monitored.stop_reason:
                    state = 'STOPPED_' + monitored.stop_reason
                    break
                if any(counts.get(verdict, 0) for verdict in ('FAIL', 'UNSUPPORTED', 'INFRA_FAILURE')):
                    state = 'STOPPED_UNEXPECTED_VERDICT'
                    break
                if not finite_complete:
                    state = ('STOPPED_SAFETY_TIMEOUT' if manifest['state'] == 'COMPLETE_BUDGET'
                             else 'STOPPED_' + manifest['state'])
                    break
        except (Exception, KeyboardInterrupt) as exc:
            state = 'STOPPED_RESOURCE_LIMIT' if isinstance(exc, ResourceLimit) else 'INFRA_FAILURE'
            error = type(exc).__name__ + ': ' + str(exc)
            event('execution_failure', error=error)
        finally:
            if executor is not None:
                try:
                    close_started = time.monotonic_ns()
                    executor.close()
                    close_seconds = (time.monotonic_ns() - close_started) / 1e9
                    event('backend_closed')
                except Exception as exc:
                    state, error = 'INFRA_FAILURE', 'Executor close failed: ' + str(exc)
                    event('backend_close_failure', error=error)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            event('sample_finish', state=state, completed_jobs=len(jobs), error=error)
    journal_path.chmod(0o444)
    receipt = {'schema_version': 2, 'experiment': EXPERIMENT, 'state': state,
               'spec_sha256': hashlib.sha256(spec_bytes).hexdigest(),
               'harness_sha256': harness_sha256(), 'source_commit': spec['source_commit'],
               'image_digest': spec['image_digest'], 'backend': spec['backend'],
               'environment': environment, 'gpu_executed': bool(environment and environment.get('gpu_executed')),
               'started_utc': started_utc, 'finished_utc': utc(),
               'actual_total_seconds': (time.monotonic_ns() - started_ns) / 1e9,
               'backend_initialization_seconds': initialization_seconds,
               'backend_close_seconds': close_seconds,
               'planned_jobs': len(spec['schedule']), 'completed_jobs': len(jobs),
               'finite_work_completed_jobs': sum(job['development_finite_work_completion'] for job in jobs),
               'selected_case_target': spec['selected_case_target'],
               'safety_timeout_seconds': spec['safety_timeout_seconds'],
               'completion_rule': COMPLETION_RULE,
               'projection_targets': spec['projection_targets'],
               'jobs': jobs, 'error': error, 'execution': 'ONE_CAMPAIGN_AT_A_TIME_ONE_SHARED_EXECUTOR',
               'partition': PARTITION, 'confirmatory': False, 'comparison_schedule_changed': False,
               'establishes_shorter_comparative_budget': False, 'establishes_statistical_superiority': False,
               'external_hardware_qualification_required': spec['backend'] == 'cuda',
               'trace_byte_limit_per_job': spec['trace_byte_limit_per_job'],
               'total_trace_byte_limit': spec['total_trace_byte_limit'],
               'actual_total_trace_bytes': previous_trace_bytes,
               'minimum_free_bytes': spec['minimum_free_bytes'],
               'trace_limit_overshoot_bound': 'ONE_COMPLETE_CASE_RECORD',
               'journal_file': 'journal.jsonl',
               'journal_sha256': hashlib.sha256(journal_path.read_bytes()).hexdigest()}
    write_original(output / 'receipt.json', canonical(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['model', 'native-reference', 'cuda'], default='model')
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--spec-sha256')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--selected-case-target', type=int, default=SELECTED_CASE_TARGET)
    parser.add_argument('--safety-timeout-seconds', type=float, default=SAFETY_TIMEOUT_SECONDS)
    parser.add_argument('--write-spec', type=Path, help='Write the predeclared spec without executing a backend')
    args = parser.parse_args()
    try:
        if args.write_spec:
            payload = canonical(make_spec(args.backend, args.selected_case_target,
                                          args.safety_timeout_seconds))
            write_original(args.write_spec, payload)
            print(json.dumps({'spec_file': str(args.write_spec), 'spec_sha256': hashlib.sha256(payload).hexdigest()}))
            return 0
        if args.output is None:
            parser.error('Execution requires --output for original durable evidence')
        if args.backend == 'cuda' and (args.spec is None or not args.spec_sha256):
            parser.error('GPU sample requires --spec and its explicitly approved --spec-sha256')
        if args.spec is not None:
            payload = args.spec.read_bytes()
            if not args.spec_sha256:
                parser.error('A supplied spec requires --spec-sha256')
            spec = validate_spec(payload, args.spec_sha256, args.backend,
                                 args.selected_case_target, args.safety_timeout_seconds)
        else:
            spec = make_spec(args.backend, args.selected_case_target,
                             args.safety_timeout_seconds)
            payload = canonical(spec)
        receipt = execute_sample(spec, payload, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(receipt, indent=2))
    return 0 if receipt['state'] == 'COMPLETE_FINITE_WORK_SAMPLE' else 1


if __name__ == '__main__':
    sys.exit(main())
