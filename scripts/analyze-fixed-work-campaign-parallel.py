#!/usr/bin/env python3
"""Compose the unchanged semantic auditor across CPU processes after GPU release.

Original archives stay compressed and unchanged. Each worker independently
reopens the TAR stream and calls the original audit_job. The original analyze
function remains the sole global coordinator and statistical implementation.
"""
import argparse
import concurrent.futures
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import resource
import sys
import tarfile
import time

MAX_WORKERS = 4
WORKER_ADDRESS_SPACE = 1024 ** 3
MAX_PROOF_BYTES = 128 * 1024 ** 2
_CONTEXT = None


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


IMPORTED_ADAPTER_SHA256 = sha(Path(__file__))


def encode_row(row):
    """JSON dictionaries cannot preserve integer candidate keys; use pairs."""
    encoded = dict(row)
    pairs = []
    for index, record in sorted(row['_candidate_records'].items()):
        require(type(index) is int and index >= 0 and record['case_index'] == index
                and record['run_id'] == row['run_id'] and record['verdict'] == 'FAIL', 'Candidate index or identity differs')
        pairs.append({'case_index': index, 'record': record})
    encoded['_candidate_records'] = pairs
    return encoded


def decode_row(encoded):
    row, candidates = dict(encoded), {}
    pairs = encoded['_candidate_records']
    require(isinstance(pairs, list), 'Candidate proof requires lossless integer-index pairs')
    for pair in pairs:
        require(isinstance(pair, dict) and set(pair) == {'case_index', 'record'}, 'Malformed candidate proof pair')
        index, record = pair['case_index'], pair['record']
        require(type(index) is int and index >= 0 and index not in candidates
                and record['case_index'] == index and record['run_id'] == row['run_id'] and record['verdict'] == 'FAIL',
                'Candidate proof index or identity differs')
        candidates[index] = record
    require(len(candidates) == row['candidate_failures'] == row['counts'].get('FAIL', 0), 'Candidate proof count differs')
    row['_candidate_records'] = candidates
    return row


def preflight_archive_limits(module, archive, cpu_qualification):
    """Bound retained metadata before ArchiveEvidence allocates its inventory."""
    retained = {'spec.json', 'receipt.json', 'journal.jsonl', 'manifest.json', 'start.json', 'checkpoint.json',
        'run-fixed-work-campaign.py', 'run-work-sample.py', 'fixed-work-campaign-v0.3.md', 'comparison-schedule.json', 'SHA256SUMS'}
    root = 'evidence' if cpu_qualification else 'cc-contract-evidence'
    names, file_count, metadata_bytes, declared_bytes = set(), 0, 0, 0
    require(Path(archive).stat().st_size <= 8 * 1024 ** 3, 'Original compressed archive exceeds the collected cap')
    with tarfile.open(archive, 'r|gz') as stream:
        for member in stream:
            name = module.ArchiveEvidence.safe_name(member.name, root)
            require(name not in names and len(name.encode()) <= 4096
                    and (member.isdir() or member.isfile()), 'Unsafe duplicate, linked or oversized archive member')
            names.add(name)
            require(len(names) <= 10000, 'Bounded original archive member count exceeded')
            if not member.isfile():
                continue
            file_count += 1
            declared_bytes += member.size
            require(file_count <= 10000 and member.size >= 0 and declared_bytes <= 40 * 1024 ** 3,
                    'Bounded original file count or uncompressed volume exceeded')
            if Path(name).name in retained:
                metadata_bytes += member.size
                limit = 16 * module.METADATA_LIMIT if name.endswith('/journal.jsonl') else module.METADATA_LIMIT
                require(member.size <= limit and metadata_bytes <= MAX_PROOF_BYTES, 'Bounded original retained metadata volume exceeded')
    return {'files': file_count, 'retained_metadata_bytes': metadata_bytes, 'declared_uncompressed_bytes': declared_bytes}


def validate_deallocation_receipt(module, campaign, archive, collection, deallocation_receipt):
    require(deallocation_receipt is not None, 'GPU archive review requires an original deallocation receipt')
    require(Path(deallocation_receipt).name == 'release.json'
            and Path(deallocation_receipt).resolve().parent == Path(collection).resolve().parent
            and Path(archive).resolve().parent == Path(collection).resolve().parent,
            'Deallocation must be the retained original from this campaign collection directory')
    before_identity, before_sha = identity(deallocation_receipt), sha(deallocation_receipt)
    release = read_proof(deallocation_receipt)
    require(release.get('power_state') == 'PowerState/deallocated', 'GPU must be deallocated before parallel CPU review')
    require(module.utc(release['timestamp_utc']) >= module.utc(campaign['finished_utc']), 'Deallocation receipt predates this GPU campaign')
    require(identity(deallocation_receipt) == before_identity and sha(deallocation_receipt) == before_sha,
            'Original deallocation receipt changed during gate verification')
    return before_identity, before_sha


def write_new(path, value):
    data = canonical(value)
    require(len(data) <= MAX_PROOF_BYTES, 'Bounded worker evidence size exceeded')
    with Path(path).open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    Path(path).chmod(0o444)


def read_proof(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_PROOF_BYTES, 'Missing or oversized worker evidence')
    return json.loads(path.read_bytes())


def identity(path):
    row = Path(path).stat()
    return {'device': row.st_dev, 'inode': row.st_ino, 'bytes': row.st_size, 'mtime_ns': row.st_mtime_ns}


def ranges(count, workers):
    require(type(workers) is int and 1 <= workers <= MAX_WORKERS and type(count) is int and 0 <= count <= 140,
            'Bounded CPU worker/job count required')
    return [(i * count // workers, (i + 1) * count // workers) for i in range(workers) if i * count // workers < (i + 1) * count // workers]


def source_bindings(repo):
    repo = Path(repo).resolve(strict=True)
    files = [repo / 'scripts/analyze-fixed-work-campaign.py', repo / 'scripts/analyze-campaigns.py',
             repo / 'scripts/run-fixed-work-campaign.py', repo / 'scripts/run-work-sample.py',
             repo / 'docs/methodology/fixed-work-campaign-v0.3.md', repo / 'experiments/comparison-schedule.json']
    files += sorted((repo / 'src').rglob('*.py'))
    return {str(path.relative_to(repo)): sha(path) for path in files}


def load_analysis(repo, expected_sha):
    repo = Path(repo).resolve(strict=True)
    path = repo / 'scripts/analyze-fixed-work-campaign.py'
    require(sha(path) == expected_sha, 'Expected unchanged analyzer SHA differs')
    before_sources = source_bindings(repo)
    sys.path.insert(0, str(repo / 'src'))
    loader = importlib.util.spec_from_file_location('parallel_original_fixed_work_analysis', path)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    require(source_bindings(repo) == before_sources, 'Semantic source changed during import')
    for name, imported in list(sys.modules.items()):
        if name.startswith('cc_contract') and getattr(imported, '__file__', None):
            require(Path(imported.__file__).resolve().is_relative_to(repo / 'src'), 'Semantic package loaded from another source')
    return module


def clone_stream(module, original):
    clone = object.__new__(module.ArchiveEvidence)
    clone.__dict__ = {key: value for key, value in original.__dict__.items() if key not in ('stream', 'iterator')}
    clone.stream = tarfile.open(clone.path, 'r|gz')
    clone.iterator = iter(clone.stream)
    return clone


def audit_range(bounds):
    """Worker called only after one complete original archive inventory pass."""
    context = _CONTEXT
    require(context is not None, 'CPU worker context missing')
    resource.setrlimit(resource.RLIMIT_AS, (WORKER_ADDRESS_SPACE, WORKER_ADDRESS_SPACE))
    module, evidence = context['module'], clone_stream(context['module'], context['evidence'])
    first, stop = bounds
    started, rows = time.monotonic(), []
    progress = context['proof_directory'] / ('progress-%03d-%03d.jsonl' % bounds)
    proof = context['proof_directory'] / ('jobs-%03d-%03d.json' % bounds)
    try:
        with progress.open('x') as stream:
            for i in range(first, stop):
                entry = context['entries'][i]
                interrupted = context['interrupted'] and i == len(context['entries']) - 1
                row = module.audit_job(evidence, entry, context['spec'], context['campaign_started_ns'], interrupted)
                rows.append({'job_index': i, 'entry_sha256': digest(entry), 'spec_sha256': context['spec_sha256'],
                    'campaign_started_ns': context['campaign_started_ns'], 'final_interrupted_job': interrupted, 'row': encode_row(row)})
                stream.write(canonical({'job_index': i, 'run_id': row['run_id'], 'selected_cases': row['selected_cases'],
                    'raw_sha256': row['raw_sha256'], 'elapsed_seconds': time.monotonic() - started}).decode())
                stream.flush()
                os.fsync(stream.fileno())
        value = {'schema_version': 1, 'bounds': list(bounds), 'original_archive_sha256': context['archive_sha256'],
            'original_inventory_sha256': context['inventory_sha256'], 'original_source_bindings_sha256': context['sources_sha256'],
            'original_receipt_sha256': context['receipt_sha256'], 'rows': rows, 'elapsed_seconds': time.monotonic() - started,
            'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
        write_new(proof, value)
        return {'file': str(proof), 'sha256': sha(proof), 'bounds': list(bounds)}
    finally:
        evidence.close()


class AuditedDispatch:
    """Return exactly once the original audit_job result for the original call."""
    def __init__(self, evidence, entries, spec, campaign_started_ns, interrupted, proof_rows):
        require(len(proof_rows) == len(entries), 'Independent worker job inventory missing or duplicated')
        self.rows = {}
        for proof in proof_rows:
            i = proof['job_index']
            require(type(i) is int and i not in self.rows and 0 <= i < len(entries), 'Duplicate or invalid worker job index')
            expected_interrupted = interrupted and i == len(entries) - 1
            require(proof['entry_sha256'] == digest(entries[i]) and proof['spec_sha256'] == digest(spec)
                    and proof['campaign_started_ns'] == campaign_started_ns and proof['final_interrupted_job'] is expected_interrupted,
                    'Worker result is not bound to the exact original call')
            row = proof['row']
            require(row['run_id'] == entries[i]['run_id'] and row['seed'] == entries[i]['configuration']['seed']
                    and row['method'] == entries[i]['configuration']['method'] and row['block'] == entries[i]['configuration']['block']
                    and row['raw_sha256'] == entries[i]['raw_sha256'], 'Worker audited result identity differs')
            self.rows[i] = proof
        require(set(self.rows) == set(range(len(entries))), 'Worker job ranges have a gap')
        self.evidence, self.entries, self.spec = evidence, entries, spec
        self.started, self.interrupted, self.calls = campaign_started_ns, interrupted, []

    def __call__(self, evidence, entry, spec, campaign_started_ns, final_interrupted_job=False):
        i = len(self.calls)
        require(i < len(self.entries) and evidence is self.evidence and entry == self.entries[i] and spec == self.spec
                and campaign_started_ns == self.started
                and final_interrupted_job is (self.interrupted and i == len(self.entries) - 1),
                'Global coordinator dispatch does not match original chronological call')
        self.calls.append(i)
        return copy.deepcopy(self.rows[i]['row'])


def parallel_analyze(module, repo, archive, collection, output, expected_sha, workers=4,
                     cpu_qualification=False, deallocation_receipt=None, reviews=None):
    global _CONTEXT
    require(sha(Path(__file__)) == IMPORTED_ADAPTER_SHA256, 'Offline adapter changed since import')
    require(sha(Path(repo) / 'scripts/analyze-fixed-work-campaign.py') == expected_sha, 'Analyzer changed before CPU review')
    require('fork' in multiprocessing.get_all_start_methods(), 'Independent Unix CPU process support required')
    ranges(0, workers)
    archive, output = Path(archive), Path(output)
    require(not archive.is_symlink() and not output.exists(), 'Original archive symlink or existing output forbidden')
    proof_directory = output.with_name(output.stem + '-workers')
    receipt_path = output.with_name(output.stem + '-parallel-receipt.json')
    require(not proof_directory.exists() and not receipt_path.exists(), 'A fresh offline review directory is required')
    output.parent.mkdir(parents=True, exist_ok=True)
    proof_directory.mkdir(mode=0o700)
    before_identity, before_sha, before_sources = identity(archive), sha(archive), source_bindings(repo)
    source_digest, collection_sha = digest(before_sources), sha(collection)
    evidence = None
    worker_receipts, failure, verified, release_sha, release_identity, preflight = [], None, False, None, None, None
    started = time.monotonic()
    try:
        preflight = preflight_archive_limits(module, archive, cpu_qualification)
        evidence = module.ArchiveEvidence(archive, collection, cpu_qualification)
        require(evidence.files and len(evidence.files) <= 10000
                and sum(len(data) for data in evidence.metadata.values()) <= MAX_PROOF_BYTES, 'Bounded original metadata inventory exceeded')
        spec = module.metadata(evidence.file('spec.json'))
        campaign = module.metadata(evidence.file('receipt.json'))
        entries = campaign['jobs']
        require(len(entries) <= 140 and all(entry['job_index'] == i for i, entry in enumerate(entries)), 'Original job indices missing or duplicated')
        module.validate_spec(spec, Path(repo) / 'docs/methodology/fixed-work-campaign-v0.3.md',
            Path(repo) / 'experiments/comparison-schedule.json', Path(repo) / 'scripts/run-fixed-work-campaign.py',
            Path(repo) / 'scripts/run-work-sample.py')
        if spec['backend'] == 'cuda':
            require(not cpu_qualification and deallocation_receipt is not None, 'GPU archive review requires an original deallocation receipt')
            release_identity, release_sha = validate_deallocation_receipt(module, campaign, archive, collection, deallocation_receipt)
        else:
            require(cpu_qualification and campaign['gpu_executed'] is False, 'CPU qualification archive must remain explicitly CPU only')
        inventory_sha = digest(evidence.files)
        context = {'module': module, 'evidence': evidence, 'proof_directory': proof_directory, 'entries': entries,
            'spec': spec, 'spec_sha256': digest(spec), 'campaign_started_ns': campaign['started_monotonic_ns'],
            'interrupted': campaign['state'] == 'PARTIAL_INTERRUPTED', 'archive_sha256': before_sha,
            'inventory_sha256': inventory_sha, 'sources_sha256': source_digest,
            'receipt_sha256': module.sha(evidence.file('receipt.json'))}
        # Never fork a live shared gzip descriptor. Each worker constructs its
        # own read-only stream; the parent coordinator only needs cached metadata.
        evidence.close()
        _CONTEXT = context
        partitions = ranges(len(entries), workers)
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('fork')) as pool:
            futures = [pool.submit(audit_range, bounds) for bounds in partitions]
            worker_receipts = [future.result() for future in futures]
        proof_rows = []
        for worker in worker_receipts:
            require(sha(worker['file']) == worker['sha256'], 'Worker proof file changed')
            proof = read_proof(worker['file'])
            require(sha(worker['file']) == worker['sha256'], 'Worker proof file changed during reading')
            require(proof['bounds'] == worker['bounds'] and proof['original_archive_sha256'] == before_sha
                    and proof['original_inventory_sha256'] == inventory_sha and proof['original_source_bindings_sha256'] == source_digest
                    and proof['original_receipt_sha256'] == context['receipt_sha256'], 'Worker proof input bindings differ')
            first, stop = proof['bounds']
            require([row['job_index'] for row in proof['rows']] == list(range(first, stop)), 'Worker range missing or reordered')
            for item in proof['rows']:
                item['row'] = decode_row(item['row'])
            proof_rows.extend(proof['rows'])
        dispatch = AuditedDispatch(evidence, entries, spec, context['campaign_started_ns'], context['interrupted'], proof_rows)
        original_job_auditor = module.audit_job
        try:
            module.audit_job = dispatch
            result = module.analyze(evidence, reviews=reviews)
        finally:
            module.audit_job = original_job_auditor
        require(dispatch.calls == list(range(len(entries))), 'Global coordinator did not consume every audited job once')
        require(identity(archive) == before_identity and sha(archive) == before_sha and sha(collection) == collection_sha
                and source_bindings(repo) == before_sources and sha(Path(__file__)) == IMPORTED_ADAPTER_SHA256,
                'Original archive, collection or source changed during review')
        if release_sha is not None:
            require(identity(deallocation_receipt) == release_identity and sha(deallocation_receipt) == release_sha,
                    'Original deallocation receipt changed during CPU review')
        result.update(original_archive_sha256=before_sha, original_collection_receipt_sha256=collection_sha,
            original_files_verified=evidence.verified_original_file_count, raw_archive_extraction_performed=False,
            original_host_hash_manifest_verified=evidence.original_host_hash_manifest_verified,
            cpu_qualification_archive_adapter=evidence.cpu_qualification)
        write_new(output, result)
        verified = True
        return result
    except BaseException as error:
        failure = type(error).__name__
        raise
    finally:
        if evidence is not None:
            evidence.close()
        _CONTEXT = None
        write_new(receipt_path, {'schema_version': 1, 'state': 'VERIFIED_COMPOSED_OFFLINE_CPU_AUDIT' if verified else 'FAILED_COMPOSED_OFFLINE_CPU_AUDIT',
            'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'scope': ('CPU_ARCHIVE_QUALIFICATION_ONLY_NO_GPU_EXECUTION' if cpu_qualification
                      else 'CPU_EVIDENCE_RECOMPUTATION_ONLY_AFTER_GPU_DEALLOCATION'),
            'gpu_compute_performed_by_adapter': False, 'deallocation_gate_verified': release_sha is not None,
            'gpu_jobs_parallel': False, 'CPU_review_parallel_processes': workers, 'analyzer_sha256': expected_sha,
            'adapter_sha256': IMPORTED_ADAPTER_SHA256, 'adapter_final_sha256': sha(Path(__file__)), 'original_archive_sha256': before_sha,
            'original_archive_identity': before_identity, 'original_collection_receipt_sha256': collection_sha,
            'original_source_bindings_sha256': source_digest, 'original_source_bindings': before_sources,
            'deallocation_receipt_sha256': release_sha, 'deallocation_receipt_identity': release_identity,
            'deallocation_proof_limit': 'Retained original controller release state and timestamp in the same campaign collection directory; no independent live Azure power readback by this offline adapter.',
            'archive_preflight': preflight, 'worker_address_space_limit_bytes': WORKER_ADDRESS_SPACE,
            'workers': worker_receipts, 'elapsed_seconds': time.monotonic() - started, 'error_type': failure,
            'raw_archive_extraction_performed': False, 'result_sha256': sha(output) if verified else None})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--expected-analyzer-sha256', required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--collection-json', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--cpu-qualification-archive', action='store_true')
    parser.add_argument('--deallocation-receipt', type=Path)
    parser.add_argument('--reviews', type=Path)
    args = parser.parse_args()
    module = load_analysis(args.repo_root, args.expected_analyzer_sha256)
    result = parallel_analyze(module, args.repo_root, args.archive, args.collection_json, args.output,
        args.expected_analyzer_sha256, args.workers, args.cpu_qualification_archive, args.deallocation_receipt, args.reviews)
    print(json.dumps({'state': result['state'], 'audited_jobs': result['audited_jobs'], 'audited_selected_cases': result['audited_selected_cases']}))


if __name__ == '__main__':
    main()
