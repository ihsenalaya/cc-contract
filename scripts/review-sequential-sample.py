#!/usr/bin/env python3
"""Audit immutable development evidence in streams after releasing the GPU.

This checks original traces against a deferred CPU model. Descriptive throughput
does not establish absolute GPU correctness, statistical superiority, or a
shorter reserved comparison budget. CPU fixtures never become GPU evidence.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import tarfile
import time

from cc_contract.cli import canonical
from cc_contract.contracts import validate, InvalidScenario
from cc_contract.generators import FAMILIES, features
from cc_contract.model import execute
from cc_contract.search import METHODS, Search, schedule


ROOT = 'cc-contract-evidence/'
PREFIX = ROOT + 'sequential-sample/runs/'
INPUT = ROOT + 'sample-inputs/'
IMAGE = 'ghcr.io/ihsenalaya/cc-contract-ir@sha256:e09597869dab698d082cc56ceb5cbb7c6eb348760e08f617387491837ad1fc8a'
SOURCE = '1f62b1838196e495d715c1cf063b03ea777aaa94'
PARTITION = 'development_sequential_throughput_pilot'
EXPERIMENT = 'SEQUENTIAL_THROUGHPUT_DEVELOPMENT_PILOT'
SEED = 9100901
METADATA_LIMIT = 2 * 1024 * 1024
LINE_LIMIT = 64 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(name):
    require(isinstance(name, str) and name and '\\' not in name, 'Unsafe archive path')
    parts = PurePosixPath(name).parts
    require(not name.startswith('/') and all(p not in ('.', '..') for p in name.rstrip('/').split('/')),
            'Unsafe archive path')
    require(parts and parts[0] == 'cc-contract-evidence', 'Archive path outside evidence root')
    return name.rstrip('/')


def parse_utc(value):
    require(isinstance(value, str), 'Missing UTC timestamp')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0, 'Timestamp must be UTC')
    return stamp.timestamp()


def finite_number(value, positive=False):
    return (type(value) in (int, float) and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def read_metadata(stream, size):
    require(size <= METADATA_LIMIT, 'Metadata exceeds bounded size')
    data = stream.read(METADATA_LIMIT + 1)
    require(len(data) == size, 'Metadata size mismatch')
    return data


def inventory(path):
    """One archive pass hashes every original file without loading raw traces."""
    files, metadata, names = {}, {}, set()
    with tarfile.open(path, 'r|gz') as archive:
        for member in archive:
            name = safe_name(member.name)
            require(name not in names, 'Duplicate archive member')
            names.add(name)
            require(member.isdir() or member.isfile(), 'Archive links or special members are forbidden')
            if member.isdir():
                continue
            require(member.size >= 0, 'Invalid archive file size')
            stream = archive.extractfile(member)
            digest = hashlib.sha256()
            retain = (name == ROOT + 'SHA256SUMS' or name.startswith(INPUT)
                      or (name.startswith(PREFIX) and name.endswith(
                          ('/spec.json', '/receipt.json', '/journal.jsonl', '/manifest.json', '/start.json'))))
            if retain:
                data = read_metadata(stream, member.size)
                digest.update(data)
                metadata[name] = data
            else:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            files[name] = {'sha256': digest.hexdigest(), 'bytes': member.size}
    require(ROOT + 'SHA256SUMS' in metadata, 'Missing original host hash manifest')
    expected = {}
    for line in metadata[ROOT + 'SHA256SUMS'].decode().splitlines():
        require(re.fullmatch(r'[a-f0-9]{64}  \./[^\n]+', line) is not None, 'Malformed host hash record')
        digest, relative = line.split('  ', 1)
        name = safe_name(ROOT + relative[2:])
        require(name not in expected, 'Duplicate host hash record')
        expected[name] = digest
    require(set(expected) == set(files) - {ROOT + 'SHA256SUMS'}, 'Original host hash inventory mismatch')
    require(all(files[name]['sha256'] == digest for name, digest in expected.items()), 'Original file hash mismatch')
    return files, metadata


def check_spec(bundle, metadata):
    require(bundle.get('transport') == 'SEQUENTIAL_IR_SAMPLE', 'Not an approved sequential sample bundle')
    payload = metadata.get(INPUT + 'spec.json')
    require(payload is not None and hashlib.sha256(payload).hexdigest() == bundle.get('sample_spec_sha256'),
            'Sample spec hash differs from approved bundle')
    require(metadata.get(PREFIX + 'spec.json') == payload, 'Executed spec differs from approved input')
    script = metadata.get(INPUT + 'run-sequential-sample.py')
    require(script is not None and hashlib.sha256(script).hexdigest() == bundle.get('sample_harness_sha256'),
            'Executed harness hash differs from approved bundle')
    spec = json.loads(payload)
    require(spec['schema_version'] == 1 and spec['experiment'] == EXPERIMENT, 'Unexpected sample schema')
    require(spec['schedule_seed'] == SEED and spec['oracle_version'] == 'integer_physical_tag_v2', 'Sample seed/oracle mismatch')
    require(spec['harness_sha256'] == bundle['sample_harness_sha256'], 'Spec harness hash mismatch')
    require(spec['confirmatory'] is False and spec['comparison_schedule_changed'] is False,
            'Development sample must not become a confirmatory comparison')
    require(spec['trace_byte_limit_per_job'] == 256 * 1024 * 1024
            and spec['minimum_free_bytes'] == 2 * 1024 * 1024 * 1024, 'Resource bounds differ from declaration')
    jobs = spec['schedule']
    require(isinstance(jobs, list) and len(jobs) == 14, 'Exactly fourteen predeclared sample jobs required')
    budget = jobs[0]['budget_seconds']
    require(finite_number(budget, True) and budget <= 60, 'Invalid sample budget')
    expected = [{**job, 'block': None, 'sample_block': job['block'], 'partition': PARTITION}
                for job in schedule(2, budget, SEED)]
    require(jobs == expected, 'Sample order, seeds, partition, or budget differs from declaration')
    require(not ({j['seed'] for j in jobs} & {j['seed'] for j in schedule()}), 'Reserved seeds reused by development sample')
    require(spec['backend'] in ('cuda', 'model', 'native-reference'), 'Unsupported sample backend')
    if spec['backend'] == 'cuda':
        require(budget == 60 and spec['image_digest'] == IMAGE and bundle['images']['ir'] == IMAGE,
                'GPU sample requires the pinned immutable IR image and sixty-second budgets')
        require(spec['source_commit'] == SOURCE, 'GPU source commit differs from qualified image')
    else:
        require(re.fullmatch(r'[a-f0-9]{40}', spec['source_commit']) is not None, 'CPU source commit must be recorded')
    return spec


def check_receipt(spec, receipt, metadata):
    require(receipt['schema_version'] == 1 and receipt['experiment'] == EXPERIMENT, 'Receipt schema mismatch')
    for field in ('source_commit', 'image_digest', 'backend', 'harness_sha256'):
        require(receipt[field] == spec[field], 'Receipt identity differs from spec: ' + field)
    require(receipt['spec_sha256'] == hashlib.sha256(metadata[PREFIX + 'spec.json']).hexdigest(), 'Receipt spec hash mismatch')
    require(receipt['execution'] == 'ONE_CAMPAIGN_AT_A_TIME_ONE_SHARED_EXECUTOR', 'Parallel execution is not this sample')
    require(receipt['partition'] == PARTITION and receipt['confirmatory'] is False
            and receipt['comparison_schedule_changed'] is False
            and receipt['establishes_shorter_comparative_budget'] is False
            and receipt['establishes_statistical_superiority'] is False, 'Receipt overstates development scope')
    require(receipt['planned_jobs'] == 14 and receipt['completed_jobs'] == len(receipt['jobs']) <= 14, 'Job count mismatch')
    full = receipt['state'] == 'COMPLETE_SAMPLE'
    require((full and len(receipt['jobs']) == 14) or (not full and
            (receipt['state'].startswith('STOPPED_') or receipt['state'] == 'INFRA_FAILURE')),
            'Missing jobs must be explicitly partial')
    require(not full or receipt['error'] is None, 'Complete sample still reports an execution error')
    require(finite_number(receipt['actual_total_seconds']), 'Invalid total sample duration')
    begin, finish = parse_utc(receipt['started_utc']), parse_utc(receipt['finished_utc'])
    require(finish >= begin, 'Sample wall-clock interval reversed')
    environment = receipt['environment']
    gpu = spec['backend'] == 'cuda'
    if environment is not None:
        require(environment['gpu_executed'] is gpu and receipt['gpu_executed'] is gpu, 'CPU/GPU execution scope mismatch')
        require(environment['scope'] == ('REAL_CUDA_IR' if gpu else
                ('CPU_SIMULATION_ONLY' if spec['backend'] == 'model' else 'CPU_NATIVE_REFERENCE_ONLY')),
                'Unexpected execution scope')
    else:
        require(not receipt['jobs'] and not full and receipt['gpu_executed'] is False, 'Missing execution environment')
    previous_end_ns, previous_end_utc, ids = None, None, set()
    for index, entry in enumerate(receipt['jobs']):
        require(entry['job_index'] == index and entry['configuration'] == spec['schedule'][index], 'Job order/configuration mismatch')
        require(entry['run_id'] not in ids and re.fullmatch(r'campaign-[A-Za-z0-9_.-]+', entry['run_id']), 'Duplicate or unsafe campaign identity')
        ids.add(entry['run_id'])
        require(entry['manifest_file'] == entry['run_id'] + '/manifest.json'
                and entry['raw_file'] == entry['run_id'] + '/records.jsonl', 'Campaign evidence path mismatch')
        low, high = entry['started_monotonic_ns'], entry['finished_monotonic_ns']
        require(type(low) is int and type(high) is int and 0 <= low < high, 'Invalid monotonic job interval')
        utc_low, utc_high = parse_utc(entry['started_utc']), parse_utc(entry['finished_utc'])
        require(begin <= utc_low <= utc_high <= finish, 'Job outside sample UTC interval')
        require(previous_end_ns is None or low >= previous_end_ns, 'Sequential job monotonic intervals overlap')
        require(previous_end_utc is None or utc_low >= previous_end_utc, 'Sequential job UTC intervals overlap')
        previous_end_ns, previous_end_utc = high, utc_high
    if receipt['jobs']:
        span = (receipt['jobs'][-1]['finished_monotonic_ns'] - receipt['jobs'][0]['started_monotonic_ns']) / 1e9
        require(receipt['actual_total_seconds'] >= span, 'Total sample duration excludes enclosed jobs')
    require(receipt['journal_file'] == 'journal.jsonl', 'Unexpected journal path')
    journal_data = metadata.get(PREFIX + 'journal.jsonl')
    require(journal_data is not None and hashlib.sha256(journal_data).hexdigest() == receipt['journal_sha256'], 'Journal hash mismatch')
    journal = [json.loads(line) for line in journal_data.splitlines()]
    require(journal and journal[0]['event'] == 'sample_start' and journal[-1]['event'] == 'sample_finish', 'Journal bounds missing')
    require(journal[-1]['state'] == receipt['state'] and journal[-1]['completed_jobs'] == len(receipt['jobs']), 'Journal final state mismatch')
    if full:
        require(sum(event['event'] == 'backend_ready' for event in journal) == 1
                and sum(event['event'] == 'backend_closed' for event in journal) == 1
                and not any(event['event'] in ('execution_failure', 'backend_close_failure') for event in journal),
                'Complete sample does not have one qualified and closed backend')
        ready = next(event for event in journal if event['event'] == 'backend_ready')
        require(ready['environment'] == environment, 'Backend journal environment mismatch')
        if gpu:
            require(ready['capabilities'].get('mapped') is True and ready['capabilities'].get('graphs') is True,
                    'GPU journal lacks required capability qualification')
        require(finite_number(receipt['backend_initialization_seconds'])
                and finite_number(receipt['backend_close_seconds']), 'Backend initialization/close timings missing')
    previous_ns, previous_utc = None, None
    starts, ends = {}, {}
    for event in journal:
        stamp, ns = parse_utc(event['timestamp_utc']), event['monotonic_ns']
        require(type(ns) is int and ns >= 0 and (previous_ns is None or ns >= previous_ns), 'Journal monotonic order mismatch')
        require(previous_utc is None or stamp >= previous_utc, 'Journal UTC order mismatch')
        previous_ns, previous_utc = ns, stamp
        if event['event'] in ('job_start', 'job_finish'):
            target = starts if event['event'] == 'job_start' else ends
            require(event['job_index'] not in target, 'Duplicate journal job event')
            target[event['job_index']] = event
    require(set(ends) == set(range(len(receipt['jobs']))), 'Journal completed job inventory mismatch')
    permitted_starts = (set(ends),) if full else (set(ends), set(ends) | {len(receipt['jobs'])})
    require(set(starts) in permitted_starts, 'Journal started job inventory mismatch')
    for entry in receipt['jobs']:
        index = entry['job_index']
        require(starts[index]['configuration'] == entry['configuration'], 'Journal job configuration mismatch')
        require(all(ends[index].get(key) == value for key, value in entry.items()), 'Journal completed entry mismatch')
        require(entry['started_monotonic_ns'] <= starts[index]['monotonic_ns'] <= entry['finished_monotonic_ns'], 'Journal start outside job interval')
        require(ends[index]['monotonic_ns'] >= entry['finished_monotonic_ns'], 'Journal finish precedes job completion')
    return full


def review_campaign(stream, member_size, manifest, start, entry, spec, environment):
    for key, value in start.items():
        require(manifest.get(key) == value, 'Original start/manifest identity mismatch')
    require(manifest['schema_version'] == 2 and manifest['run_id'] == entry['run_id'], 'Campaign schema/identity mismatch')
    require(manifest['configuration'] == entry['configuration'] and manifest['configuration']['block'] is None
            and manifest['configuration']['partition'] == PARTITION, 'Campaign is not the declared development job')
    require(manifest['image_digest'] == spec['image_digest'] and manifest['git_commit'] == spec['source_commit'], 'Campaign image/source mismatch')
    require(manifest['working_tree_dirty'] is not True and manifest['oracle_version'] == spec['oracle_version'], 'Unqualified source/oracle')
    require(manifest['environment']['scope'] == environment['scope'] and
            manifest['environment']['gpu_executed'] is environment['gpu_executed'], 'Campaign execution scope mismatch')
    require(manifest['state'] == entry['state'] and manifest['raw_file'] == 'records.jsonl'
            and manifest['raw_sha256'] == entry['raw_sha256'], 'Campaign evidence links mismatch')
    require(manifest['confirmed_defects'] == [] and manifest['time_to_confirmed_detection'] is None
            and manifest['nondetection_is_censored'] is True, 'Candidates must not become confirmed defects')
    actual = manifest['actual_seconds']
    require(finite_number(actual, True), 'Invalid campaign duration')
    require(actual <= (entry['finished_monotonic_ns'] - entry['started_monotonic_ns']) / 1e9 + .01,
            'Campaign duration exceeds enclosing job interval')
    if manifest['state'] == 'COMPLETE_BUDGET':
        require(actual >= entry['configuration']['budget_seconds'], 'Complete campaign did not exhaust declared budget')
    else:
        require(manifest['state'] in ('INTERRUPTED', 'INFRA_FAILURE'), 'Unexpected partial GPU campaign state')
    support = manifest['family_support']
    require(set(support) == set(FAMILIES) and all(type(v) is bool for v in support.values()), 'Malformed family support')
    if spec['backend'] == 'cuda':
        require(all(support.values()), 'GPU sample requires all qualified families')
    policy = Search(entry['configuration']['method'], entry['configuration']['seed'], [f for f in FAMILIES if support[f]])
    counts, structural, temporal = Counter(), set(), set()
    total, observations, last_elapsed, digest = 0, 0, 0, hashlib.sha256()
    while True:
        line = stream.readline(LINE_LIMIT + 1)
        if not line:
            break
        require(len(line) <= LINE_LIMIT and line.endswith(b'\n'), 'Oversized or truncated trace record')
        digest.update(line)
        record = json.loads(line)
        require(canonical(record) == line, 'Case record is not canonical original JSON')
        require(record['record_type'] == 'case' and record['case_index'] == total
                and record['run_id'] == manifest['run_id'], 'Case identity/order mismatch')
        require(record['scope'] == environment['scope'] and record['gpu_executed'] is environment['gpu_executed'], 'Case execution scope mismatch')
        require(record['confirmed_distinct_defect'] is False, 'Unreviewed case claims a confirmed defect')
        elapsed, duration = record['elapsed_seconds'], record['duration_seconds']
        require(finite_number(elapsed) and finite_number(duration) and last_elapsed <= elapsed <= actual + .01
                and duration <= elapsed + .01, 'Invalid case timing')
        last_elapsed = elapsed
        stamp = parse_utc(record['timestamp_utc'])
        require(parse_utc(entry['started_utc']) <= stamp <= parse_utc(entry['finished_utc']), 'Case timestamp outside job interval')
        scenario = record['scenario']
        require(scenario == policy.next(), 'Scenario differs from deterministic declared policy/seed')
        verdict, observed = record['verdict'], record['observations']
        try:
            validate(scenario)
            legal = True
        except InvalidScenario as exc:
            legal = False
            require(verdict == 'INVALID_TEST' and not observed and record['reason'] == str(exc), 'Invalid input sent to device or misclassified')
        if legal:
            require(verdict in ('PASS', 'FAIL', 'UNSUPPORTED', 'INFRA_FAILURE'), 'Legal input has an invalid classification')
            if verdict in ('PASS', 'FAIL'):
                reference = execute(scenario)
                require(len(observed) == len(reference), 'Independent observation count mismatch')
                failures = False
                for measured, expected in zip(observed, reference):
                    require(measured['buffer'] == expected['buffer'] and measured['expected'] == expected['expected'],
                            'Reported reference contradicts independent deferred model')
                    require(measured.get('scope', environment['scope']) == environment['scope']
                            and measured.get('gpu_executed', environment['gpu_executed']) is environment['gpu_executed'],
                            'Observation execution scope mismatch')
                    physical = measured['observed']
                    require(isinstance(physical, dict) and set(physical) == {'values', 'generation'}
                            and type(physical['generation']) is int and isinstance(physical['values'], list)
                            and len(physical['values']) == len(expected['observed']['values'])
                            and all(type(value) is int and -(2**31) <= value < 2**31 for value in physical['values']),
                            'Physical payload/generation is not a bounded integer observation')
                    good = measured['observed'] == expected['observed']
                    require(measured['verdict'] == ('PASS' if good else 'FAIL'), 'Observation verdict contradicts independently recomputed payload/tag')
                    failures |= not good
                require(verdict == ('FAIL' if failures else 'PASS'), 'Case verdict contradicts independent observations')
                observations += len(observed)
                policy.observe(scenario)
                keys, transitions = features(scenario)
                structural |= keys
                temporal |= transitions
            else:
                require(not observed and isinstance(record['reason'], str) and record['reason'], 'Missing explicit unsupported/infrastructure reason')
        counts[verdict] += 1
        total += 1
    require(digest.hexdigest() == manifest['raw_sha256'], 'Raw case hash mismatch')
    require(total == manifest['completed_cases'] and dict(counts) == manifest['counts'], 'Campaign case/count aggregate mismatch')
    require(manifest['state'] != 'COMPLETE_BUDGET' or total > 0, 'Complete campaign contains no executed or rejected case')
    require(policy.draws == manifest['candidate_draws'] and manifest['coverage'] ==
            {'structural': len(structural), 'temporal': len(temporal)}, 'Campaign search/coverage aggregate mismatch')
    require(entry['diagnostics']['completed_cases'] == total and entry['diagnostics']['counts'] == dict(counts)
            and entry['diagnostics']['actual_seconds'] == actual, 'Receipt diagnostics mismatch')
    diagnostics = entry['diagnostics']
    require(diagnostics['candidate_draws'] == policy.draws and diagnostics['coverage'] == manifest['coverage']
            and diagnostics['cases_per_second'] == total / actual
            and diagnostics['passing_cases_per_second'] == counts['PASS'] / actual
            and diagnostics['candidate_draws_per_second'] == policy.draws / actual
            and diagnostics['invalid_fraction'] == (counts['INVALID_TEST'] / total if total else None)
            and diagnostics['confirmed_defects'] == [] and diagnostics['diagnostic_only'] is True,
            'Receipt throughput/coverage diagnostics mismatch')
    return {'job_index': entry['job_index'], 'sample_block': entry['configuration']['sample_block'],
            'method': entry['configuration']['method'], 'seed': entry['configuration']['seed'],
            'state': manifest['state'], 'actual_seconds': actual, 'budget_seconds': entry['configuration']['budget_seconds'],
            'cases': total, 'passing_cases': counts['PASS'], 'invalid_proposals': counts['INVALID_TEST'],
            'candidate_failures': counts['FAIL'], 'observations': observations, 'candidate_draws': policy.draws,
            'counts': dict(counts), 'raw_bytes': member_size, 'coverage': manifest['coverage'],
            'gpu_passing_cases_per_second': counts['PASS'] / actual if environment['gpu_executed'] else None,
            'diagnostic_passing_cases_per_second': counts['PASS'] / actual,
            'confirmed_defects': [], 'independently_recomputed': True}


def review(directory):
    started = time.monotonic()
    directory = Path(directory)
    collection = json.loads((directory / 'collection.json').read_text())
    bundle = json.loads((directory / 'workload-bundle.json').read_text())
    filename = collection['archive_file']
    require(isinstance(filename, str) and Path(filename).name == filename, 'Archive path escapes protected window')
    archive_path = directory / filename
    require(not archive_path.is_symlink() and sha(archive_path) == collection['archive_sha256'], 'Original archive hash mismatch')
    files, metadata = inventory(archive_path)
    require(len(files) - 1 == collection['files_verified'], 'Collection file count mismatch')
    spec = check_spec(bundle, metadata)
    require(PREFIX + 'receipt.json' in metadata, 'Missing sample receipt; sample did not finish exporting')
    receipt = json.loads(metadata[PREFIX + 'receipt.json'])
    full = check_receipt(spec, receipt, metadata)
    if spec['backend'] == 'cuda':
        release_path = directory / 'release.json'
        require(release_path.is_file() and not release_path.is_symlink(), 'Offline GPU audit requires a deallocation receipt first')
        release = json.loads(release_path.read_text())
        require(release['power_state'] == 'PowerState/deallocated'
                and parse_utc(release['timestamp_utc']) >= parse_utc(receipt['finished_utc']),
                'GPU release was not confirmed after this sample')
    rows, targets = [], {}
    for entry in receipt['jobs']:
        manifest_path = PREFIX + entry['manifest_file']
        require(manifest_path in metadata and PREFIX + entry['raw_file'] in files, 'Campaign evidence missing')
        start_path = PREFIX + entry['run_id'] + '/start.json'
        require(start_path in metadata, 'Original campaign start missing')
        expected_artifacts = {entry['run_id'] + '/' + name for name in
                              ('start.json', 'records.jsonl', 'checkpoint.json', 'manifest.json')}
        manifest = json.loads(metadata[manifest_path])
        if manifest['completed_cases'] == 0 and PREFIX + entry['run_id'] + '/checkpoint.json' not in files:
            expected_artifacts.remove(entry['run_id'] + '/checkpoint.json')
        require({a['file'] for a in entry['artifacts']} == expected_artifacts
                and len(entry['artifacts']) == len(expected_artifacts), 'Job original artifact inventory mismatch')
        for artifact in entry['artifacts']:
            original = files.get(PREFIX + artifact['file'])
            require(original is not None and original['bytes'] == artifact['bytes']
                    and original['sha256'] == artifact['sha256'], 'Job original artifact hash/size mismatch')
        targets[PREFIX + entry['raw_file']] = (entry, manifest, json.loads(metadata[start_path]))
    orphan_traces = sorted(name for name in files if name.startswith(PREFIX + 'campaign-')
                           and name.endswith('/records.jsonl') and name not in targets)
    require(not full or not orphan_traces, 'Complete sample contains unlisted original campaign traces')
    with tarfile.open(archive_path, 'r|gz') as archive:
        for member in archive:
            if member.name in targets:
                entry, manifest, start = targets.pop(member.name)
                rows.append(review_campaign(archive.extractfile(member), member.size, manifest, start,
                                            entry, spec, receipt['environment']))
    require(not targets and len(rows) == len(receipt['jobs']), 'Not every completed campaign was audited')
    rows.sort(key=lambda row: row['job_index'])
    unexpected = any(any(row['counts'].get(v, 0) for v in ('FAIL', 'UNSUPPORTED', 'INFRA_FAILURE')) for row in rows)
    require(not full or (all(row['state'] == 'COMPLETE_BUDGET' for row in rows) and not unexpected),
            'Complete sample contains partial campaigns or unexpected verdicts')
    summary = {}
    for method in METHODS:
        selected = [row for row in rows if row['method'] == method]
        rates = [row['diagnostic_passing_cases_per_second'] for row in selected]
        summary[method] = {'observed_jobs': len(selected), 'planned_jobs': 2, 'job_rates': rates,
                          'minimum_observed_rate': min(rates) if rates else None,
                          'maximum_observed_rate': max(rates) if rates else None,
                          'variance_or_power_established': False}
    gpu = spec['backend'] == 'cuda'
    result = {'schema_version': 1, 'experiment': EXPERIMENT,
              'state': ('PASS_GPU_SAMPLE_AUDIT' if gpu else 'PASS_CPU_DIAGNOSTIC_AUDIT') if full else 'PARTIAL_SAMPLE_AUDIT',
              'original_state': receipt['state'], 'gpu_executed': receipt['gpu_executed'],
              'scope': receipt['environment']['scope'] if receipt['environment'] else 'NO_EXECUTION',
              'archive_sha256': collection['archive_sha256'], 'spec_sha256': receipt['spec_sha256'],
              'source_commit': spec['source_commit'], 'image_digest': spec['image_digest'],
              'harness_sha256': spec['harness_sha256'], 'planned_jobs': 14, 'audited_jobs': len(rows),
              'nonoverlapping_job_intervals_verified': True, 'all_original_file_hashes_verified': True,
              'trace_review': 'STREAMED_INDEPENDENT_DEFERRED_MODEL_AND_POLICY_RECOMPUTATION',
              'unlisted_partial_trace_files': orphan_traces,
              'all_case_traces_independently_recomputed': not orphan_traces,
              'jobs': rows, 'descriptive_by_method': summary,
              'actual_sample_seconds': receipt['actual_total_seconds'],
              'backend_initialization_seconds': receipt['backend_initialization_seconds'],
              'backend_close_seconds': receipt['backend_close_seconds'],
              'campaign_seconds': sum(row['actual_seconds'] for row in rows),
              'raw_trace_bytes': sum(row['raw_bytes'] for row in rows),
              'rate_denominator': 'actual_campaign_wall_seconds_including_generation_validation_execution_fsync',
              'partition': PARTITION, 'confirmatory': False, 'confirmed_defects': [],
              'candidate_failures_require_fresh_replays_and_characterization': True,
              'establishes_absolute_gpu_correctness': False, 'establishes_statistical_superiority': False,
              'establishes_shorter_comparative_budget': False, 'reserved_campaign_budget_changed': False,
              'attestation_review': 'SEPARATE_REQUIRED', 'full_E0_complete': False,
              'offline_review_seconds': time.monotonic() - started}
    for filename, label in (('run-start.json', 'cloud_run_start'), ('release.json', 'cloud_release'),
                            ('run-exit.json', 'cloud_run_exit'), ('cleanup-verified.json', 'cloud_cleanup')):
        path = directory / filename
        if path.is_file() and not path.is_symlink():
            result[label] = {'receipt_sha256': sha(path), 'receipt': json.loads(path.read_text())}
    start_receipt = result.get('cloud_run_start', {}).get('receipt')
    release_receipt = result.get('cloud_release', {}).get('receipt')
    exit_receipt = result.get('cloud_run_exit', {}).get('receipt')
    result['cloud_cycle_timings'] = {'start_before_apply_to_confirmed_deallocation_seconds': None,
                                   'start_before_apply_to_run_exit_seconds': None,
                                   'local_preparation_or_review_included': False,
                                   'measured_billed_amount': None}
    if start_receipt is not None:
        beginning = parse_utc(start_receipt['timestamp_utc'])
        if release_receipt is not None:
            duration = parse_utc(release_receipt['timestamp_utc']) - beginning
            require(duration >= 0 and release_receipt['power_state'] == 'PowerState/deallocated', 'Invalid cloud release timing')
            result['cloud_cycle_timings']['start_before_apply_to_confirmed_deallocation_seconds'] = duration
        if exit_receipt is not None:
            require(exit_receipt['started_at_utc'] == start_receipt['timestamp_utc']
                    and finite_number(exit_receipt['elapsed_seconds'])
                    and parse_utc(exit_receipt['finished_at_utc']) >= beginning, 'Invalid cloud run timing')
            result['cloud_cycle_timings']['start_before_apply_to_run_exit_seconds'] = exit_receipt['elapsed_seconds']
    phases_path = directory / 'run-phases.jsonl'
    if phases_path.is_file() and not phases_path.is_symlink():
        require(phases_path.stat().st_size <= METADATA_LIMIT, 'Cloud phase journal exceeds bounded size')
        result['cloud_phase_journal_sha256'] = sha(phases_path)
        result['cloud_phases'] = [json.loads(line) for line in phases_path.read_bytes().splitlines()]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = review(args.directory)
    with args.output.open('xb') as stream:
        stream.write(canonical(result))
    args.output.chmod(0o444)
    print(json.dumps({'state': result['state'], 'gpu_executed': result['gpu_executed'],
                      'audited_jobs': result['audited_jobs'], 'review_sha256': sha(args.output)}))
    return 0 if result['state'].startswith('PASS_') else 1


if __name__ == '__main__':
    raise SystemExit(main())
