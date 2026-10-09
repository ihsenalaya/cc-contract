#!/usr/bin/env python3
"""Independently audit protocol v0.3 original traces, then describe paired blocks.

Raw files are streamed and never rewritten. CPU fixtures, development pilots,
partial quotas and unreviewed candidate FAILs cannot become complete GPU
comparisons. The original runner's legacy completion label remains unchanged.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import statistics
import tarfile
from types import SimpleNamespace

from cc_contract.cli import canonical
from cc_contract.contracts import InvalidScenario, validate
from cc_contract.generators import FAMILIES, features
from cc_contract.model import execute
from cc_contract.search import METHODS, Search, schedule


ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'ghcr.io/ihsenalaya/cc-contract-ir@sha256:e09597869dab698d082cc56ceb5cbb7c6eb348760e08f617387491837ad1fc8a'
SOURCE = '1f62b1838196e495d715c1cf063b03ea777aaa94'
PARTITION = 'fixed_selected_case_evaluation'
COMPLETION = 'FIXED_SELECTED_CASES_INCLUDING_INVALID_TEST'
LEGACY_STATE = 'COMPLETE_CASE_LIMIT_LOCAL_ONLY'
METADATA_LIMIT = 2 * 1024 * 1024
LINE_LIMIT = 64 * 1024 * 1024
BOOTSTRAP_SEED = 59001
BOOTSTRAP_DRAWS = 5000

loader = importlib.util.spec_from_file_location('fixed_work_statistics', ROOT / 'scripts/analyze-campaigns.py')
stats = importlib.util.module_from_spec(loader)
loader.loader.exec_module(stats)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') if hasattr(path, 'open') else Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def number(value, positive=False):
    return type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def utc(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0, 'Timestamp must be UTC')
    return stamp.timestamp()


def safe_file(directory, relative):
    require(isinstance(relative, str) and relative and '\\' not in relative, 'Unsafe evidence path')
    name = PurePosixPath(relative)
    require(not name.is_absolute() and all(p not in ('', '.', '..') for p in relative.split('/')), 'Unsafe evidence path')
    if isinstance(directory, ArchiveEvidence):
        return directory.file(relative)
    base = Path(directory).resolve()
    path = base.joinpath(*name.parts)
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(base), 'Missing or unsafe evidence file')
    return path


def metadata(path):
    path = path if hasattr(path, 'stat') else Path(path)
    require(path.stat().st_size <= METADATA_LIMIT, 'Metadata exceeds bounded size')
    return json.loads(path.read_bytes())


class ArchiveFile:
    """A bounded metadata file or the current forward-only raw member."""
    def __init__(self, evidence, name):
        self.evidence, self.name = evidence, name

    def stat(self):
        return SimpleNamespace(st_size=self.evidence.files[self.name]['bytes'])

    def read_bytes(self):
        require(self.name in self.evidence.metadata, 'Archive file is not retained bounded metadata')
        return self.evidence.metadata[self.name]

    def open(self, mode='rb'):
        require(mode == 'rb', 'Archive evidence is read-only')
        if self.name in self.evidence.metadata:
            return io.BytesIO(self.read_bytes())
        return self.evidence.open_raw(self.name)

    def is_file(self):
        return True

    def relative_to(self, directory):
        require(directory is self.evidence, 'Archive relative path has a different root')
        return PurePosixPath(self.name[len(self.evidence.prefix):])

    def __eq__(self, other):
        return isinstance(other, ArchiveFile) and self.evidence is other.evidence and self.name == other.name


class ArchiveEvidence:
    """Inventory/hash pass, then a separate sequential trace audit pass.

    No raw trace is extracted or retained in memory. Hash and member inventory
    verification happen before analysis. Original paths are never executed.
    """
    def __init__(self, archive_path, collection_path, cpu_qualification=False):
        self.path = Path(archive_path)
        self.cpu_qualification = cpu_qualification
        self.root = 'evidence' if cpu_qualification else 'cc-contract-evidence'
        collection = metadata(Path(collection_path))
        require(collection['archive_file'] == self.path.name and collection['archive_sha256'] == sha(self.path), 'Collection archive identity/hash mismatch')
        self.files, self.metadata, names = {}, {}, set()
        retained_names = {'spec.json', 'receipt.json', 'journal.jsonl', 'manifest.json', 'start.json', 'checkpoint.json',
                          'run-fixed-work-campaign.py', 'run-work-sample.py', 'fixed-work-campaign-v0.3.md', 'comparison-schedule.json', 'SHA256SUMS'}
        with tarfile.open(self.path, 'r|gz') as archive:
            for member in archive:
                name = self.safe_name(member.name, self.root)
                require(name not in names, 'Duplicate archive member')
                names.add(name)
                require(member.isdir() or member.isfile(), 'Archive links and special files are forbidden')
                if member.isdir():
                    continue
                require(member.size >= 0, 'Invalid archive member size')
                stream = archive.extractfile(member)
                digest = hashlib.sha256()
                if PurePosixPath(name).name in retained_names:
                    limit = 16 * METADATA_LIMIT if name.endswith('/journal.jsonl') else METADATA_LIMIT
                    require(member.size <= limit, 'Archive metadata exceeds bounded size')
                    data = stream.read(limit + 1)
                    require(len(data) == member.size, 'Archive metadata size mismatch')
                    self.metadata[name] = data
                    digest.update(data)
                else:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                self.files[name] = {'sha256': digest.hexdigest(), 'bytes': member.size}
        sums_name = self.root + '/SHA256SUMS'
        self.original_host_hash_manifest_verified = sums_name in self.metadata
        require(self.original_host_hash_manifest_verified or cpu_qualification, 'Missing original SHA256SUMS')
        expected = {}
        for line in self.metadata.get(sums_name, b'').decode().splitlines():
            require(re.fullmatch(r'[a-f0-9]{64}  \./[^\n]+', line) is not None, 'Malformed host hash record')
            digest, relative = line.split('  ', 1)
            name = self.safe_name(self.root + '/' + relative[2:], self.root)
            require(name not in expected, 'Duplicate host hash record')
            expected[name] = digest
        if self.original_host_hash_manifest_verified:
            require(set(expected) == set(self.files) - {sums_name}
                    and all(self.files[name]['sha256'] == digest for name, digest in expected.items()), 'Original archive file hash/inventory mismatch')
        self.verified_original_file_count = len(self.files) - int(self.original_host_hash_manifest_verified)
        require(collection['files_verified'] == self.verified_original_file_count, 'Collection verified file count mismatch')
        receipts = [name for name, data in self.metadata.items() if name.endswith('/receipt.json')
                    and json.loads(data).get('schema_version') == 3 and json.loads(data).get('partition') == PARTITION]
        require(len(receipts) == 1, 'Exactly one fixed-work campaign receipt required; pilots cannot be pooled')
        self.prefix = receipts[0][:-len('receipt.json')]
        if cpu_qualification:
            spec = json.loads(self.metadata[self.prefix + 'spec.json'])
            receipt = json.loads(self.metadata[receipts[0]])
            require(spec['backend'] in ('model', 'native-reference') and receipt['gpu_executed'] is False,
                    'CPU-only archive adapter cannot become GPU evidence')
        self.stream = tarfile.open(self.path, 'r|gz')
        self.iterator = iter(self.stream)

    @staticmethod
    def safe_name(name, root='cc-contract-evidence'):
        require(isinstance(name, str) and name and '\\' not in name and not name.startswith('/'), 'Unsafe archive path')
        cleaned = name.rstrip('/')
        parts = cleaned.split('/')
        require(parts[0] == root and all(p not in ('', '.', '..') for p in parts), 'Unsafe archive path')
        return cleaned

    def file(self, relative):
        name = self.prefix + relative
        require(name in self.files, 'Missing original archive evidence file')
        return ArchiveFile(self, name)

    def glob(self, pattern):
        require(pattern == 'campaign-*/*', 'Unexpected archive inventory pattern')
        for name in self.files:
            if name.startswith(self.prefix + 'campaign-') and name[len(self.prefix):].count('/') == 1:
                yield ArchiveFile(self, name)

    def open_raw(self, wanted):
        for member in self.iterator:
            if member.isfile() and self.safe_name(member.name, self.root) == wanted:
                return self.stream.extractfile(member)
        raise ValueError('Raw archive members are missing or not in declared sequential order')

    def close(self):
        self.stream.close()


def validate_spec(spec, protocol, legacy, harness, shared_harness):
    require(spec.get('schema_version') == 3, 'Expected v0.3 fixed-work schema')
    require(spec.get('partition') == PARTITION, 'Development or legacy partition is not fixed-work evaluation')
    require(spec.get('protocol_sha256') == sha(protocol), 'Protocol hash mismatch')
    require(spec.get('harness_sha256') == sha(harness), 'Orchestration harness hash mismatch')
    require(spec.get('shared_harness_sha256') == sha(shared_harness), 'Shared harness hash mismatch')
    require(spec.get('reserved_schedule_sha256') == sha(legacy), 'Reserved original schedule hash mismatch')
    original = metadata(legacy)
    require(len(original) == 140 and original == schedule(), 'Original reserved order or seeds changed')
    target = spec['selected_case_target']
    require(type(target) is int and 1 <= target <= 100, 'Invalid selected-case quota')
    require(spec['safety_timeout_seconds'] == 120 and spec['completion_rule'] == COMPLETION, 'Stopping rule or safety guard differs')
    require(spec['oracle_version'] == 'integer_physical_tag_v2', 'Oracle version differs')
    require(spec['overall_command_timeout_seconds'] == 3600, 'Overall command safety guard differs')
    require(spec['trace_byte_limit_per_job'] == 1024**3 and spec['total_trace_byte_limit'] == 32 * 1024**3
            and spec['minimum_free_bytes'] == 2 * 1024**3, 'Resource guards differ')
    jobs = spec['schedule']
    require(isinstance(jobs, list) and len(jobs) == 140, 'Exactly 140 predeclared jobs required')
    for declared, old in zip(jobs, original):
        require(all(declared.get(key) == old[key] for key in ('block', 'position', 'method', 'seed')), 'Reserved seed or randomized order changed')
        require(declared.get('partition') == PARTITION and declared.get('budget_seconds') == 120
                and declared.get('max_cases') == target and declared.get('selected_case_target') == target
                and declared.get('completion_rule') == COMPLETION, 'Job stopping declaration differs')
    pilot_seeds = {job['seed'] for seed in (9100901, 9100902) for job in schedule(2, seed=seed)}
    require(not (pilot_seeds & {job['seed'] for job in jobs}), 'Development pilot seeds reused')
    require(spec['backend'] in ('model', 'native-reference', 'cuda'), 'Unsupported backend')
    if spec['backend'] == 'cuda':
        require(target == 100 and spec['image_digest'] == IMAGE and spec['source_commit'] == SOURCE, 'GPU quota or pinned image/source differs')
    else:
        require(re.fullmatch(r'[a-f0-9]{40}', spec['source_commit']) is not None, 'CPU source identity missing')
    return jobs


def audit_observations(scenario, observed, verdict, reason):
    """Recompute expected observations independently of recorded expectations."""
    try:
        validate(scenario)
    except InvalidScenario as error:
        require(verdict == 'INVALID_TEST' and not observed and reason == str(error), 'Invalid input executed or misclassified')
        return False
    require(verdict in ('PASS', 'FAIL', 'UNSUPPORTED', 'INFRA_FAILURE'), 'Legal input classification invalid')
    if verdict in ('UNSUPPORTED', 'INFRA_FAILURE'):
        require(not observed and isinstance(reason, str) and reason, 'Missing unsupported/infrastructure reason')
        return False
    reference = execute(scenario)
    require(len(observed) == len(reference), 'Independent observation count mismatch')
    failures = False
    for measured, expected in zip(observed, reference):
        require(measured['buffer'] == expected['buffer'] and measured['expected'] == expected['expected'], 'Reported expected payload contradicts independent deferred model')
        physical = measured['observed']
        require(isinstance(physical, dict) and set(physical) == {'values', 'generation'}
                and type(physical['generation']) is int and isinstance(physical['values'], list)
                and len(physical['values']) == len(expected['observed']['values'])
                and all(type(value) is int and -(2**31) <= value < 2**31 for value in physical['values']), 'Physical payload/tag is malformed')
        good = physical == expected['observed']
        require(measured['verdict'] == ('PASS' if good else 'FAIL'), 'Observation verdict contradicts payload/tag')
        failures |= not good
    require(verdict == ('FAIL' if failures else 'PASS'), 'Case verdict contradicts independently recomputed observations')
    return True


def audit_job(directory, entry, spec, campaign_started_ns, final_interrupted_job=False):
    run_id = entry['run_id']
    require(re.fullmatch(r'campaign-[A-Za-z0-9_.-]+', run_id) is not None, 'Unsafe run identity')
    require(entry['manifest_file'] == run_id + '/manifest.json' and entry['raw_file'] == run_id + '/records.jsonl', 'Job evidence paths mismatch')
    manifest_path = safe_file(directory, entry['manifest_file'])
    manifest = metadata(manifest_path)
    require(manifest['configuration'] == entry['configuration'] and manifest['run_id'] == run_id, 'Manifest job configuration or identity differs')
    require(manifest['image_digest'] == spec['image_digest'] and manifest['git_commit'] == spec['source_commit'], 'Campaign pinned image/source mismatch')
    require(manifest['working_tree_dirty'] is not True and manifest['oracle_version'] == spec['oracle_version'], 'Dirty image source or oracle mismatch')
    environment = manifest['environment']
    gpu = spec['backend'] == 'cuda'
    scope = 'REAL_CUDA_IR' if gpu else ('CPU_SIMULATION_ONLY' if spec['backend'] == 'model' else 'CPU_NATIVE_REFERENCE_ONLY')
    require(environment['gpu_executed'] is gpu and environment['scope'] == scope, 'CPU/GPU execution scope mismatch')
    require(manifest['state'] == entry['state'] and manifest['raw_file'] == 'records.jsonl'
            and manifest['raw_sha256'] == entry['raw_sha256'], 'Manifest/raw links or state differ')
    require(manifest['confirmed_defects'] == [] and manifest['time_to_confirmed_detection'] is None
            and manifest['nondetection_is_censored'] is True, 'Review annotations must stay outside original manifests')
    for key, value in metadata(safe_file(directory, run_id + '/start.json')).items():
        require(manifest.get(key) == value, 'Original start and manifest differ')
    actual = manifest['actual_seconds']
    low, high = entry['started_monotonic_ns'], entry['finished_monotonic_ns']
    require(type(low) is int and type(high) is int and 0 <= low < high, 'Invalid monotonic job interval')
    wall = (high - low) / 1e9
    require(number(actual, True) and actual <= wall + .01, 'Campaign time exceeds whole-job interval')
    if 'job_wall_seconds' in entry:
        require(entry['job_wall_seconds'] == wall, 'Whole-job timing differs from monotonic interval')
    begin, end = utc(entry['started_utc']), utc(entry['finished_utc'])
    require(begin <= end, 'UTC job interval reversed')
    support = manifest['family_support']
    require(set(support) == set(FAMILIES) and all(type(v) is bool for v in support.values()), 'Malformed supported-family set')
    require(not gpu or all(support.values()), 'GPU job lacks qualified families')
    policy = Search(entry['configuration']['method'], entry['configuration']['seed'], [f for f in FAMILIES if support[f]])
    counts, total, observations, raw_bytes, last_elapsed = Counter(), 0, 0, 0, 0
    structural, temporal, candidates, quartiles, elapsed_values = set(), set(), {}, [], []
    payload_bytes = 0
    milestones = {math.ceil(spec['selected_case_target'] * k / 4) for k in (1, 2, 3, 4)}
    digest = hashlib.sha256()
    raw_path = safe_file(directory, entry['raw_file'])
    with raw_path.open('rb') as stream:
        while True:
            line = stream.readline(LINE_LIMIT + 1)
            if not line:
                break
            require(len(line) <= LINE_LIMIT and line.endswith(b'\n'), 'Oversized or truncated original case record')
            digest.update(line)
            raw_bytes += len(line)
            record = json.loads(line)
            require(canonical(record) == line, 'Case bytes are not canonical original JSON')
            require(record['record_type'] == 'case' and record['run_id'] == run_id and record['case_index'] == total, 'Case identity/order differs')
            require(record['gpu_executed'] is gpu and record['scope'] == scope and record['confirmed_distinct_defect'] is False, 'Case scope or unreviewed defect claim differs')
            elapsed, duration = record['elapsed_seconds'], record['duration_seconds']
            require(number(elapsed) and number(duration) and last_elapsed <= elapsed <= actual + .01
                    and duration <= elapsed + .01, 'Invalid case timing')
            require(begin <= utc(record['timestamp_utc']) <= end, 'Case outside whole-job UTC interval')
            last_elapsed = elapsed
            elapsed_values.append(elapsed)
            scenario = record['scenario']
            require(scenario == policy.next(), 'Scenario differs from frozen policy/seed')
            executed = audit_observations(scenario, record['observations'], record['verdict'], record['reason'])
            for observation in record['observations']:
                require(observation.get('scope', scope) == scope and observation.get('gpu_executed', gpu) is gpu, 'Observation scope mismatch')
            if executed:
                policy.observe(scenario)
                keys, transitions = features(scenario)
                structural |= keys
                temporal |= transitions
                observations += len(record['observations'])
                payload_bytes += 4 * sum(len(item['observed']['values']) for item in record['observations'])
            if record['verdict'] == 'FAIL':
                candidates[total] = record
            counts[record['verdict']] += 1
            total += 1
            require(total <= spec['selected_case_target'], 'Selected-case quota exceeded')
            if total in milestones:
                quartiles.append({'selected_cases': total, 'candidate_draws': policy.draws,
                                  'coverage': {'structural': len(structural), 'temporal': len(temporal)},
                                  'counts': dict(counts), 'elapsed_seconds_before_serialization_and_fsync': elapsed,
                                  'raw_trace_bytes': raw_bytes, 'observations': observations,
                                  'observed_integer_payload_bytes': payload_bytes,
                                  'time_basis': 'case_elapsed_before_serialization_and_fsync'})
    require(digest.hexdigest() == manifest['raw_sha256'], 'Raw integrity check failed')
    require(total == manifest['completed_cases'] and dict(counts) == manifest['counts'], 'Campaign counts differ from originals')
    require(manifest['candidate_draws'] == policy.draws and manifest['coverage'] == {'structural': len(structural), 'temporal': len(temporal)}, 'Search draws or coverage differs')
    require(policy.draws == total * (1 if entry['configuration']['method'] in ('B1', 'B2') else 16), 'Selected-case/candidate-pool allocation differs')
    artifacts = entry['artifacts']
    expected_names = {run_id + '/' + name for name in ('start.json', 'records.jsonl', 'manifest.json')}
    if total:
        expected_names.add(run_id + '/checkpoint.json')
    require(len(artifacts) == len(expected_names) and {a['file'] for a in artifacts} == expected_names, 'Original artifact inventory differs')
    for artifact in artifacts:
        file = safe_file(directory, artifact['file'])
        actual_sha = digest.hexdigest() if file == raw_path else sha(file)
        require(artifact['sha256'] == actual_sha and artifact['bytes'] == file.stat().st_size, 'Original artifact hash or byte size differs')
    if total:
        checkpoint = metadata(safe_file(directory, run_id + '/checkpoint.json'))
        require(checkpoint['run_id'] == run_id and checkpoint['completed_cases'] == total
                and checkpoint['draws'] == policy.draws and checkpoint['structural'] == sorted(structural)
                and checkpoint['temporal'] == sorted(temporal)
                and canonical(checkpoint['random_state']) == canonical(policy.rng.getstate()), 'Checkpoint generator state differs')
        require(number(checkpoint['elapsed_seconds']) and last_elapsed <= checkpoint['elapsed_seconds'] <= actual + .01, 'Checkpoint elapsed time differs')
    command_guard_expired = (high - campaign_started_ns) / 1e9 >= spec['overall_command_timeout_seconds']
    require(entry['command_guard_expired'] is command_guard_expired, 'Whole-command timeout flag contradicts monotonic interval')
    complete = (manifest['state'] == LEGACY_STATE and total == spec['selected_case_target']
                and manifest['error'] is None and not entry.get('stop_reason')
                and not command_guard_expired
                and raw_bytes < spec['trace_byte_limit_per_job']
                and not any(counts[v] for v in ('FAIL', 'UNSUPPORTED', 'INFRA_FAILURE')))
    wrapper_interrupted_after_quota = complete and final_interrupted_job and entry['fixed_work_completion'] is False
    if wrapper_interrupted_after_quota:
        complete = False
    require(entry['fixed_work_completion'] is complete, 'Fixed-work completion contradicts original state/quota')
    require(isinstance(entry.get('original_state_scope'), str) and 'LEGACY' in entry['original_state_scope'], 'Original legacy state interpretation missing')
    if manifest['state'] == 'COMPLETE_BUDGET':
        require(actual >= spec['safety_timeout_seconds'], 'Legacy budget state did not reach safety guard')
    diagnostics = entry['diagnostics']
    require(diagnostics['completed_cases'] == total and diagnostics['counts'] == dict(counts)
            and diagnostics['actual_seconds'] == actual and diagnostics['candidate_draws'] == policy.draws
            and diagnostics['coverage'] == manifest['coverage'] and diagnostics['observations'] == observations
            and diagnostics['raw_trace_bytes'] == raw_bytes
            and diagnostics['observed_integer_payload_bytes'] == payload_bytes
            and diagnostics['valid_selected_fraction'] == ((counts['PASS'] + counts['FAIL']) / total if total else None),
            'Receipt secondary diagnostics contradict original traces')
    reported_quartiles = diagnostics['progress_quartiles']
    require(len(reported_quartiles) == len(quartiles), 'Progress milestone inventory differs')
    previous_checkpoint = 0
    for reported, expected in zip(reported_quartiles, quartiles):
        elapsed = reported.get('checkpoint_elapsed_seconds_after_case_fsync')
        require(number(elapsed) and previous_checkpoint <= elapsed
                and expected['elapsed_seconds_before_serialization_and_fsync'] <= elapsed <= actual + .01,
                'Progress checkpoint time differs')
        index = expected['selected_cases'] - 1
        require(index + 1 == len(elapsed_values) or elapsed <= elapsed_values[index + 1] + .01, 'Progress checkpoint follows next case')
        require({k: v for k, v in reported.items() if k != 'checkpoint_elapsed_seconds_after_case_fsync'} == expected, 'Progress metrics differ from original traces')
        previous_checkpoint = elapsed
    return {'run_id': run_id, 'block': entry['configuration']['block'], 'method': entry['configuration']['method'],
            'seed': entry['configuration']['seed'], 'original_campaign_state': manifest['state'],
            'fixed_work_complete': complete, 'gpu_executed': gpu, 'scope': scope,
            'wrapper_interrupted_after_quota': wrapper_interrupted_after_quota,
            'selected_cases': total, 'selected_case_target': spec['selected_case_target'], 'counts': dict(counts),
            'candidate_draws': policy.draws, 'valid_selected_fraction': (counts['PASS'] + counts['FAIL']) / total if total else None,
            'coverage': manifest['coverage'], 'observations': observations, 'raw_bytes': raw_bytes,
            'actual_campaign_seconds': actual, 'actual_job_seconds': wall,
            'job_time_basis': 'monotonic_interval_including_finalization_and_original_hashes',
            'raw_sha256': digest.hexdigest(), 'confirmed_defects': 0, 'detected': False,
            'time_to_detection': None, 'censored': True, 'censor_at_actual_campaign_seconds': actual,
            'candidate_failures': len(candidates), '_candidate_records': candidates, '_manifest': manifest}


def audit_reviews(path, rows):
    """Separate external characterization plus two hashed fresh-process replays."""
    if path is None:
        return set()
    documents = metadata(path)
    require(isinstance(documents, list), 'External defect reviews must be a list')
    index = {row['run_id']: row for row in rows}
    reviewed, seen_reviews, equivalence, detections = set(), set(), {}, {}
    for document in documents:
        key = (document['run_id'], document['case_index'])
        require(key not in seen_reviews, 'Duplicate external candidate review')
        seen_reviews.add(key)
        require(document['review_state'] in ('CONFIRMED', 'REJECTED', 'INCONCLUSIVE'), 'Unknown external review state')
        require(all(isinstance(document.get(k), str) and document[k].strip() for k in ('reviewer_identity', 'rationale', 'reviewed_utc')), 'Explicit external review identity/rationale missing')
        utc(document['reviewed_utc'])
        require(document['run_id'] in index, 'Review anchor is outside this campaign')
        row = index[document['run_id']]
        original = row['_candidate_records'].get(document['case_index'])
        require(original is not None and row['gpu_executed'], 'Review anchor must be a real GPU FAIL')
        require(document['original_raw_sha256'] == row['raw_sha256'], 'External review original raw hash differs')
        if document['review_state'] != 'INCONCLUSIVE':
            reviewed.add(key)
        if document['review_state'] != 'CONFIRMED':
            continue
        require(all(isinstance(document.get(k), str) and document[k].strip() for k in ('defect_id', 'characterized_mechanism')), 'Defect equivalence requires explicit mechanism')
        defect = document['defect_id']
        require(defect not in equivalence or equivalence[defect] == document['characterized_mechanism'], 'One defect identifier has inconsistent mechanisms')
        equivalence[defect] = document['characterized_mechanism']
        reproductions = document['reproductions']
        require(isinstance(reproductions, list) and len(reproductions) >= 2, 'Two fresh process reproductions required')
        seen = {row['run_id']}
        for reproduction in reproductions:
            replay_path = safe_file(Path(path).parent, reproduction['manifest'])
            require(sha(replay_path) == reproduction['manifest_sha256'], 'Replay manifest hash differs')
            replay = metadata(replay_path)
            require(replay['run_id'] not in seen and replay['state'] == 'REPRODUCED_IN_ONE_FRESH_PROCESS'
                    and replay.get('reproduction_unit') == 'one_fresh_process; within_process_repeats_are_not_independent', 'Replay is not a fresh independently failing process')
            seen.add(replay['run_id'])
            require(replay['gpu_executed'] is True and replay['scope'] == 'REAL_CUDA_IR'
                    and replay['image_digest'] == IMAGE and replay['git_commit'] == SOURCE and replay.get('working_tree_dirty') is not True, 'Replay execution identity differs')
            require(utc(replay['timestamp_utc']) >= utc(original['timestamp_utc']), 'Replay predates original discovery')
            raw_path = safe_file(replay_path.parent, replay['raw_file'])
            digest, replay_counts, count = hashlib.sha256(), Counter(), 0
            anchor = None
            with raw_path.open('rb') as stream:
                for line in stream:
                    require(len(line) <= LINE_LIMIT and line.endswith(b'\n'), 'Oversized/truncated replay record')
                    digest.update(line)
                    case = json.loads(line)
                    require(canonical(case) == line and case['run_id'] == replay['run_id'] and case['case_index'] == count, 'Replay record identity differs')
                    require(case['gpu_executed'] is True and case['scope'] == 'REAL_CUDA_IR', 'Replay CPU/GPU scope differs')
                    audit_observations(case['scenario'], case['observations'], case['verdict'], case.get('reason'))
                    if count == reproduction['case_index']:
                        anchor = case
                    replay_counts[case['verdict']] += 1
                    count += 1
            require(digest.hexdigest() == replay['raw_sha256'] and count == replay['completed_cases']
                    and dict(replay_counts) == replay['counts'], 'Replay raw hash/count mismatch')
            require(anchor is not None and anchor['verdict'] == 'FAIL'
                    and anchor['scenario']['operations'] == original['scenario']['operations'], 'Replay did not fail the original operation sequence')
        detections.setdefault(row['run_id'], {})[defect] = min(original['elapsed_seconds'], detections.get(row['run_id'], {}).get(defect, math.inf))
    for run_id, defects in detections.items():
        row = index[run_id]
        row.update(confirmed_defects=len(defects), detected=True, time_to_detection=min(defects.values()), censored=False)
    return reviewed


def summarize(rows, full_gpu, defect_review_complete):
    """Complete paired blocks only; no subset analysis of an incomplete matrix."""
    if not full_gpu:
        return {'available': False, 'reason': 'ALL_140_GPU_JOBS_WITH_FULL_100_CASE_QUOTAS_REQUIRED', 'by_method': {}, 'paired_comparisons': {}}
    require(len(rows) == 140 and all(row['gpu_executed'] is True and row['fixed_work_complete']
            and row['selected_cases'] == 100 for row in rows), 'Full GPU summary requires every declared quota')
    keyed = {(row['block'], row['method']): row for row in rows}
    require(len(keyed) == 140 and set(keyed) == {(b, m) for b in range(20) for m in METHODS}, 'Full paired block inventory differs')
    by_method = {}
    for method in METHODS:
        group = [keyed[(block, method)] for block in range(20)]
        by_method[method] = {'independent_blocks': 20, 'selected_cases': sum(r['selected_cases'] for r in group),
                             'candidate_draws': sum(r['candidate_draws'] for r in group),
                             'mean_valid_selected_fraction': statistics.fmean(r['valid_selected_fraction'] for r in group),
                             'mean_structural_coverage': statistics.fmean(r['coverage']['structural'] for r in group),
                             'mean_temporal_coverage': statistics.fmean(r['coverage']['temporal'] for r in group),
                             'mean_actual_job_seconds': statistics.fmean(r['actual_job_seconds'] for r in group)}
        if defect_review_complete:
            by_method[method].update(mean_confirmed_distinct_defects=statistics.fmean(r['confirmed_defects'] for r in group),
                                     detecting_jobs=sum(r['detected'] for r in group),
                                     detection_probability_95_wilson=stats.wilson(sum(r['detected'] for r in group), 20))
    comparisons, pvalues = {}, {}
    metrics = {'valid_selected_fraction': lambda r: r['valid_selected_fraction'],
               'structural_coverage': lambda r: r['coverage']['structural'],
               'temporal_coverage': lambda r: r['coverage']['temporal'],
               'whole_job_seconds': lambda r: r['actual_job_seconds']}
    if defect_review_complete:
        metrics.update(confirmed_distinct_defects=lambda r: r['confirmed_defects'],
                       detection_probability=lambda r: int(r['detected']))
    for baseline in METHODS:
        if baseline == 'B4':
            continue
        pairs = [(keyed[(block, 'B4')], keyed[(block, baseline)]) for block in range(20)]
        result = {'independent_paired_blocks': 20, 'family': 'PRIMARY_B4_VS_B1_B2_B3' if baseline in ('B1', 'B2', 'B3') else 'DESCRIPTIVE_ABLATION', 'metrics': {}, 'superiority_established': False}
        for name, value in metrics.items():
            differences = [value(left) - value(right) for left, right in pairs]
            result['metrics'][name] = {'mean_paired_difference_B4_minus_baseline': statistics.fmean(differences),
                                      'paired_block_bootstrap_95_percentile_ci': stats.paired_bootstrap(differences, BOOTSTRAP_SEED, BOOTSTRAP_DRAWS)}
        if defect_review_complete and baseline in ('B1', 'B2', 'B3'):
            pvalues[baseline] = stats.mcnemar_exact([a['detected'] for a, b in pairs], [b['detected'] for a, b in pairs])
            result['mcnemar_two_sided_p'] = pvalues[baseline]
        comparisons[baseline] = result
    for baseline, adjusted in stats.holm(pvalues).items():
        comparisons[baseline]['holm_adjusted_primary_detection_p'] = adjusted
    return {'available': True, 'by_method': by_method, 'paired_comparisons': comparisons,
            'primary_defect_analysis_complete': defect_review_complete,
            'statistical_unit': 'independent_paired_campaign_block', 'bootstrap': {'seed': BOOTSTRAP_SEED, 'resamples': BOOTSTRAP_DRAWS},
            'case_count_scientific_adequacy_established': False, 'superiority_established': False}


def analyze(directory, protocol=None, legacy=None, harness=None, shared_harness=None, reviews=None):
    directory = directory if isinstance(directory, ArchiveEvidence) else Path(directory)
    protocol = Path(protocol or ROOT / 'docs/methodology/fixed-work-campaign-v0.3.md')
    legacy = Path(legacy or ROOT / 'experiments/comparison-schedule.json')
    harness = Path(harness or ROOT / 'scripts/run-fixed-work-campaign.py')
    shared_harness = Path(shared_harness or ROOT / 'scripts/run-work-sample.py')
    spec_path, receipt_path = safe_file(directory, 'spec.json'), safe_file(directory, 'receipt.json')
    spec, receipt = metadata(spec_path), metadata(receipt_path)
    jobs = validate_spec(spec, protocol, legacy, harness, shared_harness)
    if isinstance(directory, ArchiveEvidence):
        for filename, digest in ((Path(harness).name, spec['harness_sha256']),
                                 (Path(shared_harness).name, spec['shared_harness_sha256']),
                                 (Path(protocol).name, spec['protocol_sha256']),
                                 (Path(legacy).name, spec['reserved_schedule_sha256'])):
            matches = [item for name, item in directory.files.items() if PurePosixPath(name).name == filename]
            require((matches or directory.cpu_qualification) and all(item['sha256'] == digest for item in matches),
                    'Archived mounted input hash differs or is missing: ' + filename)
    require(receipt['schema_version'] == 3 and receipt['partition'] == PARTITION, 'Receipt is not fixed-work v0.3')
    require(receipt['spec_sha256'] == sha(spec_path), 'Executed spec hash mismatch')
    for field in ('protocol_sha256', 'reserved_schedule_sha256', 'harness_sha256', 'shared_harness_sha256', 'source_commit', 'image_digest', 'backend', 'selected_case_target', 'safety_timeout_seconds', 'overall_command_timeout_seconds', 'completion_rule', 'trace_byte_limit_per_job', 'total_trace_byte_limit', 'minimum_free_bytes'):
        require(receipt[field] == spec[field], 'Receipt binding differs: ' + field)
    require(receipt['execution'] == 'ONE_CAMPAIGN_AT_A_TIME_ONE_SHARED_EXECUTOR', 'Overlapping/parallel execution forbidden')
    entries = receipt['jobs']
    require(receipt['planned_jobs'] == 140 and receipt['completed_jobs'] == len(entries) <= 140, 'Receipt job inventory differs')
    complete = receipt['state'] == 'COMPLETE_FIXED_WORK_CAMPAIGN'
    require((complete and len(entries) == 140 and receipt['error'] is None) or (not complete and
            (receipt['state'].startswith(('PARTIAL_', 'STOPPED_')) or receipt['state'] == 'INFRA_FAILURE')), 'Incomplete campaign must be labelled partial')
    gpu = spec['backend'] == 'cuda'
    require(receipt['gpu_executed'] is gpu or not entries and receipt['gpu_executed'] is False, 'Receipt execution scope differs')
    begin, finish = utc(receipt['started_utc']), utc(receipt['finished_utc'])
    require(begin <= finish and number(receipt['actual_total_seconds']), 'Receipt timing invalid')
    require(type(receipt['started_monotonic_ns']) is int and type(receipt['finished_monotonic_ns']) is int
            and 0 <= receipt['started_monotonic_ns'] <= receipt['finished_monotonic_ns']
            and receipt['actual_total_seconds'] == (receipt['finished_monotonic_ns'] - receipt['started_monotonic_ns']) / 1e9,
            'Receipt total differs from enclosing monotonic interval')
    require(receipt['execution_scope'] == ('GPU_FIXED_SELECTED_CASE_E4_E5_EVALUATION' if gpu else 'CPU_ORCHESTRATION_QUALIFICATION_ONLY'), 'Receipt execution scope overstates evidence')
    for field in ('original_reserved_schedule_modified', 'completes_v0_2_wall_clock_budgets', 'statistical_power_established', 'establishes_statistical_superiority', 'establishes_absolute_hardware_correctness'):
        require(receipt[field] is False, 'Receipt contains an unestablished claim: ' + field)
    journal_path = safe_file(directory, receipt['journal_file'])
    require(receipt['journal_file'] == 'journal.jsonl' and sha(journal_path) == receipt['journal_sha256'], 'Journal hash mismatch')
    require(journal_path.stat().st_size <= 16 * METADATA_LIMIT, 'Journal exceeds bounded size')
    journal = [json.loads(line) for line in journal_path.read_bytes().splitlines()]
    require(journal and journal[0]['event'] == 'campaign_start' and journal[-1]['event'] == 'campaign_finish'
            and journal[-1]['state'] == receipt['state'] and journal[-1]['completed_jobs'] == len(entries), 'Journal bounds/final state differ')
    if complete:
        require(sum(e['event'] == 'backend_ready' for e in journal) == 1 and sum(e['event'] == 'backend_closed' for e in journal) == 1
                and not any(e['event'] in ('execution_failure', 'backend_close_failure') for e in journal), 'Complete campaign lacks one qualified and closed backend')
    ready = [e for e in journal if e['event'] == 'backend_ready']
    if entries:
        require(len(ready) == 1 and ready[0]['environment'] == receipt['environment']
                and receipt['environment']['gpu_executed'] is gpu, 'Recorded backend environment differs')
        require(not gpu or all(ready[0]['capabilities'].get(k) is True for k in ('mapped', 'graphs')), 'GPU capabilities not qualified')
    starts, ends, previous_ns, previous_utc = {}, {}, None, None
    for event in journal:
        ns = event['monotonic_ns']
        require(type(ns) is int and ns >= 0 and (previous_ns is None or ns >= previous_ns), 'Journal monotonic order invalid')
        stamp = utc(event['timestamp_utc'])
        require(previous_utc is None or stamp >= previous_utc, 'Journal UTC order invalid')
        previous_ns = ns
        previous_utc = stamp
        if event['event'] in ('job_start', 'job_finish'):
            target = starts if event['event'] == 'job_start' else ends
            require(event['job_index'] not in target, 'Duplicate journal job event')
            target[event['job_index']] = event
    require(set(ends) == set(range(len(entries))), 'Journal completed job inventory differs')
    require(set(starts) in (set(ends), set(ends) | {len(entries)}) and (not complete or set(starts) == set(ends)), 'Journal started job inventory differs')
    rows, previous_end, previous_utc_end, seen = [], None, None, set()
    for i, entry in enumerate(entries):
        require(entry['job_index'] == i and entry['configuration'] == jobs[i], 'Receipt order/configuration differs')
        require(entry['run_id'] not in seen, 'Duplicate run identity')
        seen.add(entry['run_id'])
        require(previous_end is None or entry['started_monotonic_ns'] >= previous_end, 'Sequential job intervals overlap')
        require(previous_utc_end is None or utc(entry['started_utc']) >= previous_utc_end, 'Sequential UTC intervals overlap')
        require(begin <= utc(entry['started_utc']) <= utc(entry['finished_utc']) <= finish, 'Job outside receipt interval')
        require(receipt['started_monotonic_ns'] <= entry['started_monotonic_ns'] <= entry['finished_monotonic_ns'] <= receipt['finished_monotonic_ns'], 'Job outside receipt monotonic interval')
        previous_end, previous_utc_end = entry['finished_monotonic_ns'], utc(entry['finished_utc'])
        require(starts[i]['configuration'] == entry['configuration'] and all(ends[i].get(k) == v for k, v in entry.items()), 'Journal job receipt differs')
        rows.append(audit_job(directory, entry, spec, receipt['started_monotonic_ns'],
                              receipt['state'] == 'PARTIAL_INTERRUPTED' and i == len(entries) - 1))
    require(receipt['finite_work_completed_jobs'] == sum(r['fixed_work_complete'] for r in rows), 'Receipt completed-quota count differs')
    require(receipt['actual_total_trace_bytes'] == sum(r['raw_bytes'] for r in rows), 'Receipt trace volume differs')
    require(receipt['actual_selected_cases'] == sum(r['selected_cases'] for r in rows), 'Receipt selected-case count differs')
    if rows:
        span = (entries[-1]['finished_monotonic_ns'] - entries[0]['started_monotonic_ns']) / 1e9
        require(receipt['actual_total_seconds'] >= span, 'Receipt total excludes enclosed job intervals')
    require(not complete or all(r['fixed_work_complete'] for r in rows), 'Complete receipt contains partial quota')
    require(not complete or sum(r['raw_bytes'] for r in rows) < spec['total_trace_byte_limit'], 'Complete receipt exceeds total trace guard')
    implementations = {(r['_manifest']['image_digest'], r['_manifest']['git_commit'], r['_manifest']['oracle_version'], canonical(r['_manifest']['family_support'])) for r in rows}
    require(len(implementations) <= 1, 'Execution implementations/support cannot be pooled')
    reviewed = audit_reviews(reviews, rows)
    candidate_keys = {(row['run_id'], i) for row in rows for i in row['_candidate_records']}
    provided_reviews = {(item['run_id'], item['case_index']) for item in metadata(reviews)} if reviews else set()
    unreviewed = len(candidate_keys - provided_reviews)
    unresolved = len(candidate_keys - reviewed)
    full_gpu = gpu and complete and len(rows) == 140 and all(r['fixed_work_complete'] and r['selected_cases'] == 100 for r in rows)
    summaries = summarize(rows, full_gpu, unresolved == 0)
    listed = {a['file'] for entry in entries for a in entry['artifacts']}
    unlisted = sorted(path.relative_to(directory).as_posix() for path in directory.glob('campaign-*/*') if path.is_file() and path.relative_to(directory).as_posix() not in listed)
    require(not complete or not unlisted, 'Complete campaign contains unlisted original campaign evidence')
    missing = [{'job_index': i, 'configuration': job, 'state': 'NOT_STARTED', 'censored': True, 'time_to_detection': None} for i, job in enumerate(jobs[len(rows):], len(rows))]
    for row in rows:
        del row['_candidate_records']
        del row['_manifest']
    return {'schema_version': 3, 'state': ('PASS_COMPLETE_FIXED_WORK_GPU_AUDIT' if full_gpu else
            'PASS_CPU_FIXED_WORK_DIAGNOSTIC_AUDIT' if not gpu and complete else 'PARTIAL_FIXED_WORK_AUDIT'),
            'protocol_version': '0.3', 'partition': PARTITION, 'gpu_executed': gpu,
            'image_digest': spec['image_digest'], 'source_commit': spec['source_commit'], 'oracle_version': spec['oracle_version'],
            'protocol_sha256': sha(protocol), 'spec_sha256': sha(spec_path), 'receipt_sha256': sha(receipt_path),
            'harness_sha256': sha(harness), 'shared_harness_sha256': sha(shared_harness), 'reserved_schedule_sha256': sha(legacy),
            'external_reviews_sha256': sha(reviews) if reviews else None,
            'planned_jobs': 140, 'audited_jobs': len(rows), 'full_gpu_quota_matrix': full_gpu,
            'audited_selected_cases': sum(r['selected_cases'] for r in rows), 'audited_candidate_draws': sum(r['candidate_draws'] for r in rows),
            'audited_observations': sum(r['observations'] for r in rows), 'audited_raw_bytes': sum(r['raw_bytes'] for r in rows),
            'whole_job_seconds': sum(r['actual_job_seconds'] for r in rows), 'actual_total_seconds': receipt['actual_total_seconds'],
            'job_rows': rows, 'missing_jobs': missing, 'unlisted_partial_original_files': unlisted,
            'partial_jobs': [{'run_id': r['run_id'], 'original_state': r['original_campaign_state'], 'selected_cases': r['selected_cases'], 'target': r['selected_case_target']} for r in rows if not r['fixed_work_complete']],
            'candidate_failures': sum(r['candidate_failures'] for r in rows), 'unreviewed_candidate_failures': unreviewed,
            'unresolved_candidate_failures': unresolved,
            'unresolved_includes_externally_inconclusive': True,
            'defect_analysis_state': 'INCOMPLETE_EXTERNAL_DEFECT_REVIEW' if unresolved else 'NO_UNRESOLVED_CANDIDATES',
            'external_review_performed': reviews is not None, 'summaries': summaries,
            'original_legacy_labels_preserved': True, 'raw_files_modified': False,
            'all_case_traces_independently_recomputed': not unlisted,
            'statistical_unit': 'independent_paired_campaign_block',
            'case_count_scientific_adequacy_established': False, 'whole_E0_E8_complete': False,
            'superiority_established': False, 'claim': 'NO_AUTOMATIC_SUPERIORITY_CLAIM',
            'nondetections': 'RIGHT_CENSORED_AT_ACTUAL_CAMPAIGN_END_NEVER_ZERO_TIME',
            'independent_GPU_remote_attestation_established_by_this_analysis': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', type=Path, nargs='?')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--collection-json', type=Path)
    parser.add_argument('--cpu-qualification-archive', action='store_true',
                        help='Explicit CPU-only Kind archive under evidence/runs; never CUDA evidence')
    parser.add_argument('--protocol', type=Path)
    parser.add_argument('--legacy-schedule', type=Path)
    parser.add_argument('--harness', type=Path)
    parser.add_argument('--shared-harness', type=Path)
    parser.add_argument('--reviews', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require((args.runs is not None) != (args.archive is not None), 'Choose a runs directory or --archive')
    require(args.archive is None or args.collection_json is not None, 'Archive requires --collection-json')
    require(not args.cpu_qualification_archive or args.archive is not None, 'CPU archive mode requires --archive')
    require(not args.output.exists(), 'Analysis output must be a new file')
    evidence = ArchiveEvidence(args.archive, args.collection_json, args.cpu_qualification_archive) if args.archive else args.runs
    try:
        result = analyze(evidence, args.protocol, args.legacy_schedule, args.harness, args.shared_harness, args.reviews)
        if args.archive:
            result.update(original_archive_sha256=sha(args.archive), original_collection_receipt_sha256=sha(args.collection_json),
                          original_files_verified=evidence.verified_original_file_count, raw_archive_extraction_performed=False,
                          original_host_hash_manifest_verified=evidence.original_host_hash_manifest_verified,
                          cpu_qualification_archive_adapter=evidence.cpu_qualification)
    finally:
        if isinstance(evidence, ArchiveEvidence):
            evidence.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(result))
    args.output.chmod(0o444)
    print(json.dumps({'state': result['state'], 'audited_jobs': result['audited_jobs'], 'full_gpu_quota_matrix': result['full_gpu_quota_matrix']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
