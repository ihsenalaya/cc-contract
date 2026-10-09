#!/usr/bin/env python3
"""Protocol v0.3: 20 paired blocks, seven policies, fixed selected-case work.

The immutable image's runner and physical operations are reused unchanged.
Original legacy states remain verbatim; quota completion is declared only by
this separately hashed orchestration and must be independently reviewed.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

from cc_contract.cli import canonical, provenance
from cc_contract.native import InfrastructureFailure
from cc_contract.runner import backend, campaign, utc
from cc_contract.search import METHODS, schedule


IMAGE_DIGEST = 'ghcr.io/ihsenalaya/cc-contract-ir@sha256:e09597869dab698d082cc56ceb5cbb7c6eb348760e08f617387491837ad1fc8a'
SOURCE_COMMIT = '1f62b1838196e495d715c1cf063b03ea777aaa94'
SHARED_HARNESS_SHA256 = 'adf1f2fed8d5db7230ce41bededfc1c74255031cb5baeacd4943e670e32ce489'
PROTOCOL_FILE = 'docs/methodology/fixed-work-campaign-v0.3.md'
PROTOCOL_SHA256 = '045089e31b67e3c37d0d673af2ac0544e05364441f4d0ece272571b2cfa3e890'
RESERVED_SCHEDULE_FILE = 'experiments/comparison-schedule.json'
RESERVED_SCHEDULE_SHA256 = 'dafb88fb778b115a3a9d2dcdb4f2b498b65be83136a70001b26597ff817621c3'
EXPERIMENT = 'E4_E5_FIXED_SELECTED_CASE_CAMPAIGN'
PARTITION = 'fixed_selected_case_evaluation'
COMPLETION_RULE = 'FIXED_SELECTED_CASES_INCLUDING_INVALID_TEST'
COMPLETE_STATE = 'COMPLETE_FIXED_WORK_CAMPAIGN'
SELECTED_CASE_TARGET = 100
SAFETY_TIMEOUT_SECONDS = 120
OVERALL_COMMAND_TIMEOUT_SECONDS = 3600
TRACE_BYTE_LIMIT_PER_JOB = 1073741824
TOTAL_TRACE_BYTE_LIMIT = 34359738368
MINIMUM_FREE_BYTES = 2147483648
BLOCKS = 20
SCHEDULE_SEED = 41001
_shared_cache = {}


def harness_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def load_shared_harness(helper_script=None):
    """Hash the mounted helper before importing or reusing any of its code."""
    path = Path(helper_script) if helper_script is not None else Path(__file__).with_name('run-work-sample.py')
    if hashlib.sha256(path.read_bytes()).hexdigest() != SHARED_HARNESS_SHA256:
        raise ValueError('Shared finite-work helper differs from its immutable hash')
    key = str(path.resolve())
    if key not in _shared_cache:
        loader = importlib.util.spec_from_file_location('_cc_contract_fixed_work_shared', path)
        module = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(module)
        _shared_cache[key] = module
    return _shared_cache[key]


def check_registered_documents():
    """Check local originals when available; the image only mounts the scripts."""
    root = Path(__file__).resolve().parent.parent
    for filename, digest in ((PROTOCOL_FILE, PROTOCOL_SHA256),
                             (RESERVED_SCHEDULE_FILE, RESERVED_SCHEDULE_SHA256)):
        path = root / filename
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Registered protocol or reserved schedule hash changed: ' + filename)


def campaign_schedule(selected_case_target=SELECTED_CASE_TARGET,
                      safety_timeout_seconds=SAFETY_TIMEOUT_SECONDS):
    jobs = schedule(blocks=BLOCKS, seed=SCHEDULE_SEED)
    pilot_jobs = schedule(blocks=2, seed=9100901) + schedule(blocks=2, seed=9100902)
    if {job['seed'] for job in jobs} & {job['seed'] for job in pilot_jobs}:
        raise ValueError('Reserved campaign seeds overlap development sample seeds')
    if len(jobs) != 140 or len({job['seed'] for job in jobs}) != BLOCKS:
        raise ValueError('Reserved campaign must have 20 distinct paired blocks and 140 jobs')
    return [{**job, 'budget_seconds': safety_timeout_seconds, 'partition': PARTITION,
             'max_cases': selected_case_target, 'selected_case_target': selected_case_target,
             'completion_rule': COMPLETION_RULE, 'protocol_version': '0.3',
             'protocol_sha256': PROTOCOL_SHA256} for job in jobs]


def make_spec(backend_name, selected_case_target=SELECTED_CASE_TARGET,
              safety_timeout_seconds=SAFETY_TIMEOUT_SECONDS, source_commit=None,
              helper_script=None):
    load_shared_harness(helper_script)
    check_registered_documents()
    if backend_name not in ('model', 'native-reference', 'cuda'):
        raise ValueError('Unsupported backend')
    if type(selected_case_target) is not int or not 1 <= selected_case_target <= SELECTED_CASE_TARGET:
        raise ValueError('Selected case count must be an integer from 1 to 100')
    if (type(safety_timeout_seconds) not in (int, float) or
            not 0 < safety_timeout_seconds <= SAFETY_TIMEOUT_SECONDS):
        raise ValueError('Safety timeout must be positive and at most 120 seconds')
    if backend_name == 'cuda' and (selected_case_target != SELECTED_CASE_TARGET or
                                   safety_timeout_seconds != SAFETY_TIMEOUT_SECONDS):
        raise ValueError('GPU campaign requires exactly 100 selected cases and a 120-second guard')
    return {'schema_version': 3, 'experiment': EXPERIMENT, 'backend': backend_name,
            'image_digest': IMAGE_DIGEST if backend_name == 'cuda' else
                os.environ.get('CC_IMAGE_DIGEST', 'NOT_APPLICABLE_LOCAL_PROCESS'),
            'source_commit': SOURCE_COMMIT if backend_name == 'cuda' else
                (source_commit or provenance()[0]),
            'harness_sha256': harness_sha256(), 'shared_harness_sha256': SHARED_HARNESS_SHA256,
            'protocol_version': '0.3', 'protocol_file': PROTOCOL_FILE,
            'protocol_sha256': PROTOCOL_SHA256,
            'reserved_schedule_file': RESERVED_SCHEDULE_FILE,
            'reserved_schedule_sha256': RESERVED_SCHEDULE_SHA256,
            'schedule_seed': SCHEDULE_SEED, 'blocks': BLOCKS, 'methods': list(METHODS),
            'schedule': campaign_schedule(selected_case_target, safety_timeout_seconds),
            'partition': PARTITION, 'selected_case_target': selected_case_target,
            'planned_jobs': 140, 'planned_selected_cases': 140 * selected_case_target,
            'safety_timeout_seconds': safety_timeout_seconds,
            'overall_command_timeout_seconds': OVERALL_COMMAND_TIMEOUT_SECONDS,
            'completion_rule': COMPLETION_RULE,
            'execution': 'ONE_CAMPAIGN_AT_A_TIME_ONE_SHARED_EXECUTOR',
            'original_reserved_schedule_modified': False,
            'completes_v0_2_wall_clock_budgets': False,
            'statistical_power_established': False,
            'trace_byte_limit_per_job': TRACE_BYTE_LIMIT_PER_JOB,
            'total_trace_byte_limit': TOTAL_TRACE_BYTE_LIMIT,
            'minimum_free_bytes': MINIMUM_FREE_BYTES,
            'oracle_version': 'integer_physical_tag_v2'}


def validate_spec(spec_bytes, expected_sha256, backend_name,
                  selected_case_target=SELECTED_CASE_TARGET,
                  safety_timeout_seconds=SAFETY_TIMEOUT_SECONDS, helper_script=None):
    if expected_sha256 != hashlib.sha256(spec_bytes).hexdigest():
        raise ValueError('Campaign spec hash differs from the approved hash')
    spec = json.loads(spec_bytes)
    if not isinstance(spec, dict):
        raise ValueError('Campaign spec must be an object')
    expected = make_spec(backend_name, selected_case_target, safety_timeout_seconds,
                         spec.get('source_commit'), helper_script)
    if spec != expected:
        raise ValueError('Campaign spec differs from the predeclared protocol, work or source bindings')
    if backend_name == 'cuda':
        if os.environ.get('CC_IMAGE_DIGEST') != IMAGE_DIGEST:
            raise ValueError('GPU campaign requires the pinned immutable IR image digest')
        if os.environ.get('CC_COMMIT') != SOURCE_COMMIT:
            raise ValueError('GPU campaign requires the pinned IR source commit')
    return spec


def execute_campaign(spec, spec_bytes, output, executor_factory=None,
                     campaign_function=None, helper_script=None):
    if threading.current_thread() is not threading.main_thread():
        raise ValueError('Campaign must run on the main thread for durable signal handling')
    checked = validate_spec(spec_bytes, hashlib.sha256(spec_bytes).hexdigest(), spec['backend'],
                            spec['selected_case_target'], spec['safety_timeout_seconds'], helper_script)
    if spec != checked:
        raise ValueError('Campaign object differs from its original spec bytes')
    shared = load_shared_harness(helper_script)
    executor_factory, campaign_function = executor_factory or backend, campaign_function or campaign
    started_utc, started_ns = utc(), time.monotonic_ns()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    shared.write_original(output / 'spec.json', spec_bytes)
    jobs, executor, monitored = [], None, None
    previous_trace_bytes = 0
    state, error, environment = 'PARTIAL_INFRA_FAILURE', None, None
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

        event('campaign_start', planned_jobs=140, protocol_sha256=PROTOCOL_SHA256)
        try:
            reason = shared.resource_limit_reason(output, spec)
            if reason:
                raise shared.ResourceLimit(reason)
            initialization_started = time.monotonic_ns()
            executor = executor_factory(spec['backend'])
            initialization_seconds = (time.monotonic_ns() - initialization_started) / 1e9
            environment = executor.environment
            if spec['backend'] == 'cuda':
                if environment.get('gpu_executed') is not True or not all(
                        executor.capabilities.get(feature) is True for feature in ('mapped', 'graphs')):
                    raise InfrastructureFailure('GPU campaign requires externally qualified CUDA T01-T08 support')
            elif environment.get('gpu_executed') is not False:
                raise InfrastructureFailure('CPU qualification executor unexpectedly reports GPU execution')
            monitored = shared.StopAfterCandidate(executor)
            event('backend_ready', environment=environment, capabilities=executor.capabilities)
            state = COMPLETE_STATE
            for index, config in enumerate(spec['schedule']):
                if interrupted['value']:
                    state = 'PARTIAL_INTERRUPTED'
                    break
                if (time.monotonic_ns() - started_ns) / 1e9 >= spec['overall_command_timeout_seconds']:
                    state = 'PARTIAL_COMMAND_TIMEOUT'
                    break
                reason = shared.resource_limit_reason(output, spec, previous_trace_bytes=previous_trace_bytes)
                if reason:
                    raise shared.ResourceLimit(reason)
                begin_utc, begin_ns = utc(), time.monotonic_ns()
                event('job_start', job_index=index, configuration=config)
                diagnostics = shared.CaseDiagnostics(config['selected_case_target'])
                with shared.guarded_case_records(monitored, output, spec, diagnostics, previous_trace_bytes):
                    manifest = campaign_function(monitored, config, output, max_cases=config['max_cases'])
                artifacts = shared.original_artifacts(output, manifest, config)
                raw_artifact = next(item for item in artifacts if item['file'].endswith('/records.jsonl'))
                if (dict(diagnostics.counts) != manifest['counts'] or
                        sum(diagnostics.counts.values()) != manifest['completed_cases'] or
                        diagnostics.raw_trace_bytes != raw_artifact['bytes']):
                    raise InfrastructureFailure('Streaming original-case diagnostics disagree with manifest')
                finish_ns, finish_utc = time.monotonic_ns(), utc()
                if jobs and begin_ns < jobs[-1]['finished_monotonic_ns']:
                    raise InfrastructureFailure('Sequential job timestamps overlap')
                command_guard_expired = (finish_ns - started_ns) / 1e9 >= spec['overall_command_timeout_seconds']
                finite_complete = (
                    manifest['state'] == 'COMPLETE_CASE_LIMIT_LOCAL_ONLY' and
                    manifest['completed_cases'] == config['selected_case_target'] and
                    not monitored.stop_reason and not interrupted['value'] and not command_guard_expired and
                    manifest.get('error') is None and
                    not any(manifest['counts'].get(verdict, 0)
                            for verdict in ('FAIL', 'UNSUPPORTED', 'INFRA_FAILURE')))
                metrics = shared.job_diagnostics(manifest, diagnostics)
                metrics.pop('diagnostic_only')
                metrics['secondary_outcomes_only'] = True
                metrics['valid_selected_fraction'] = (
                    (manifest['counts'].get('PASS', 0) + manifest['counts'].get('FAIL', 0)) /
                    manifest['completed_cases'] if manifest['completed_cases'] else None)
                entry = {'job_index': index, 'configuration': config,
                         'started_utc': begin_utc, 'finished_utc': finish_utc,
                         'started_monotonic_ns': begin_ns, 'finished_monotonic_ns': finish_ns,
                         'job_wall_seconds': (finish_ns - begin_ns) / 1e9,
                         'run_id': manifest['run_id'], 'state': manifest['state'],
                         'manifest_file': manifest['run_id'] + '/manifest.json',
                         'raw_file': manifest['run_id'] + '/' + manifest['raw_file'],
                         'raw_sha256': manifest['raw_sha256'], 'artifacts': artifacts,
                         'fixed_work_completion': finite_complete,
                         'original_state_scope': 'IMMUTABLE_RUNNER_LEGACY_LABEL_INTERPRETED_UNDER_PROTOCOL_0_3',
                         'stop_reason': monitored.stop_reason,
                         'command_guard_expired': command_guard_expired, 'diagnostics': metrics}
                jobs.append(entry)
                previous_trace_bytes += diagnostics.raw_trace_bytes
                event('job_finish', **entry)
                if monitored.stop_reason:
                    state = 'PARTIAL_' + monitored.stop_reason
                    break
                if interrupted['value']:
                    state = 'PARTIAL_INTERRUPTED'
                    break
                if any(manifest['counts'].get(verdict, 0) for verdict in ('FAIL', 'UNSUPPORTED', 'INFRA_FAILURE')):
                    state = 'PARTIAL_UNEXPECTED_VERDICT'
                    break
                if command_guard_expired:
                    state = 'PARTIAL_COMMAND_TIMEOUT'
                    break
                if not finite_complete:
                    state = ('PARTIAL_SAFETY_TIMEOUT' if manifest['state'] == 'COMPLETE_BUDGET'
                             else 'PARTIAL_' + manifest['state'])
                    break
        except (Exception, KeyboardInterrupt) as exc:
            state = 'PARTIAL_RESOURCE_LIMIT' if isinstance(exc, shared.ResourceLimit) else 'PARTIAL_INFRA_FAILURE'
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
                    state, error = 'PARTIAL_INFRA_FAILURE', 'Executor close failed: ' + str(exc)
                    event('backend_close_failure', error=error)
            if interrupted['value'] and state == COMPLETE_STATE:
                state = 'PARTIAL_INTERRUPTED'
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            event('campaign_finish', state=state, completed_jobs=len(jobs), error=error)
    journal_path.chmod(0o444)
    finished_ns, finished_utc = time.monotonic_ns(), utc()
    complete_jobs = sum(job['fixed_work_completion'] for job in jobs)
    if state == COMPLETE_STATE and (len(jobs) != 140 or complete_jobs != 140):
        raise InfrastructureFailure('Full campaign completion requires all 140 predeclared jobs')
    receipt = {'schema_version': 3, 'experiment': EXPERIMENT, 'state': state,
               'protocol_version': '0.3', 'protocol_sha256': PROTOCOL_SHA256,
               'reserved_schedule_sha256': RESERVED_SCHEDULE_SHA256,
               'spec_sha256': hashlib.sha256(spec_bytes).hexdigest(),
               'harness_sha256': harness_sha256(), 'shared_harness_sha256': SHARED_HARNESS_SHA256,
               'source_commit': spec['source_commit'], 'image_digest': spec['image_digest'],
               'backend': spec['backend'], 'environment': environment,
               'gpu_executed': bool(environment and environment.get('gpu_executed')),
               'execution_scope': ('GPU_FIXED_SELECTED_CASE_E4_E5_EVALUATION' if spec['backend'] == 'cuda'
                                   else 'CPU_ORCHESTRATION_QUALIFICATION_ONLY'),
               'started_utc': started_utc, 'finished_utc': finished_utc,
               'started_monotonic_ns': started_ns, 'finished_monotonic_ns': finished_ns,
               'actual_total_seconds': (finished_ns - started_ns) / 1e9,
               'backend_initialization_seconds': initialization_seconds,
               'backend_close_seconds': close_seconds,
               'planned_jobs': 140, 'completed_jobs': len(jobs), 'finite_work_completed_jobs': complete_jobs,
               'planned_selected_cases': spec['planned_selected_cases'],
               'selected_case_target': spec['selected_case_target'],
               'actual_selected_cases': sum(job['diagnostics']['completed_cases'] for job in jobs),
               'safety_timeout_seconds': spec['safety_timeout_seconds'],
               'overall_command_timeout_seconds': spec['overall_command_timeout_seconds'],
               'per_job_timeout_scope': 'RUNNER_LOOP_BOUNDARY_NOT_HARD_JOB_WALL_DEADLINE',
               'overall_timeout_requires_external_command_guard': True,
               'completion_rule': COMPLETION_RULE, 'jobs': jobs, 'error': error,
               'execution': spec['execution'], 'partition': PARTITION,
               'original_reserved_schedule_modified': False,
               'completes_v0_2_wall_clock_budgets': False,
               'statistical_power_established': False, 'establishes_statistical_superiority': False,
               'establishes_absolute_hardware_correctness': False,
               'confirmed_defects_require_external_reproduction_and_review': True,
               'external_hardware_qualification_required': spec['backend'] == 'cuda',
               'trace_byte_limit_per_job': spec['trace_byte_limit_per_job'],
               'total_trace_byte_limit': spec['total_trace_byte_limit'],
               'actual_total_trace_bytes': previous_trace_bytes, 'minimum_free_bytes': spec['minimum_free_bytes'],
               'trace_limit_overshoot_bound': 'ONE_COMPLETE_CASE_RECORD',
               'journal_file': 'journal.jsonl',
               'journal_sha256': hashlib.sha256(journal_path.read_bytes()).hexdigest()}
    shared.write_original(output / 'receipt.json', canonical(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['model', 'native-reference', 'cuda'], default='model')
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--spec-sha256')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--helper-script', type=Path)
    parser.add_argument('--selected-case-target', type=int, default=SELECTED_CASE_TARGET)
    parser.add_argument('--safety-timeout-seconds', type=float, default=SAFETY_TIMEOUT_SECONDS)
    parser.add_argument('--write-spec', type=Path)
    args = parser.parse_args()
    try:
        shared = load_shared_harness(args.helper_script)
        if args.write_spec:
            payload = canonical(make_spec(args.backend, args.selected_case_target, args.safety_timeout_seconds,
                                          helper_script=args.helper_script))
            shared.write_original(args.write_spec, payload)
            print(json.dumps({'spec_file': str(args.write_spec), 'spec_sha256': hashlib.sha256(payload).hexdigest()}))
            return 0
        if args.output is None:
            parser.error('Execution requires --output for original durable evidence')
        if args.backend == 'cuda' and (args.spec is None or not args.spec_sha256):
            parser.error('GPU campaign requires --spec and its explicitly approved --spec-sha256')
        if args.spec is not None:
            if not args.spec_sha256:
                parser.error('A supplied spec requires --spec-sha256')
            payload = args.spec.read_bytes()
            spec = validate_spec(payload, args.spec_sha256, args.backend, args.selected_case_target,
                                 args.safety_timeout_seconds, args.helper_script)
        else:
            spec = make_spec(args.backend, args.selected_case_target, args.safety_timeout_seconds,
                             helper_script=args.helper_script)
            payload = canonical(spec)
        receipt = execute_campaign(spec, payload, args.output, helper_script=args.helper_script)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(receipt, indent=2))
    return 0 if receipt['state'] == COMPLETE_STATE else 1


if __name__ == '__main__':
    sys.exit(main())
