"""CPU-only controls for the protected offline composition adapter."""
import concurrent.futures
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'scripts'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


adapter = load('parallel_fixed_work_audit', HERE / 'analyze-fixed-work-campaign-parallel.py')
fixtures = load('existing_offline_analysis_fixtures', ROOT / 'tests/unit/test_fixed_work_analysis.py')


class ParallelAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.FixedWorkAnalysisTests.setUpClass()
        cls.analyzer_sha = adapter.sha(ROOT / 'scripts/analyze-fixed-work-campaign.py')

    @classmethod
    def tearDownClass(cls):
        fixtures.FixedWorkAnalysisTests.tearDownClass()

    def setUp(self):
        self.fixture = fixtures.FixedWorkAnalysisTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.module = adapter.load_analysis(ROOT, self.analyzer_sha)
        self.spec = self.module.metadata(self.fixture.runs / 'spec.json')
        self.campaign = self.module.metadata(self.fixture.runs / 'receipt.json')
        self.entries = self.campaign['jobs']
        row = self.module.audit_job(self.fixture.runs, self.entries[0], self.spec, self.campaign['started_monotonic_ns'])
        self.proof = {'job_index': 0, 'entry_sha256': adapter.digest(self.entries[0]),
            'spec_sha256': adapter.digest(self.spec), 'campaign_started_ns': self.campaign['started_monotonic_ns'],
            'final_interrupted_job': False, 'row': row}
        self.output = self.fixture.directory / 'parallel-audit.json'

    def dispatch(self, proofs=None):
        return adapter.AuditedDispatch(self.fixture.runs, self.entries, self.spec,
            self.campaign['started_monotonic_ns'], False, [self.proof] if proofs is None else proofs)

    def run_adapter(self, archive, collection, workers=2):
        return adapter.parallel_analyze(self.module, ROOT, archive, collection, self.output,
            self.analyzer_sha, workers=workers, cpu_qualification=True)

    def test_ranges_cover_every_index_once_and_bound_worker_count(self):
        partitions = adapter.ranges(140, 4)
        self.assertEqual(partitions, [(0, 35), (35, 70), (70, 105), (105, 140)])
        self.assertEqual([i for first, stop in partitions for i in range(first, stop)], list(range(140)))
        self.assertEqual(adapter.ranges(0, 4), [])
        self.assertEqual(adapter.ranges(1, 4), [(0, 1)])
        for workers in (0, 5, True):
            with self.assertRaises(ValueError): adapter.ranges(140, workers)

    def test_dispatch_returns_exact_once_for_original_call_only(self):
        dispatch = self.dispatch()
        expected = copy.deepcopy(self.proof['row'])
        returned = dispatch(self.fixture.runs, self.entries[0], self.spec, self.campaign['started_monotonic_ns'])
        self.assertEqual(returned, expected)
        returned['coverage']['structural'] = -1
        self.assertEqual(self.proof['row'], expected)
        with self.assertRaises(ValueError):
            dispatch(self.fixture.runs, self.entries[0], self.spec, self.campaign['started_monotonic_ns'])

    def test_missing_duplicate_and_forged_proof_bindings_rejected(self):
        with self.assertRaises(ValueError): self.dispatch([])
        with self.assertRaises(ValueError): self.dispatch([self.proof, self.proof])
        for field, value in (('job_index', 1), ('entry_sha256', '0' * 64), ('spec_sha256', '0' * 64),
                ('campaign_started_ns', 0), ('final_interrupted_job', True)):
            proof = copy.deepcopy(self.proof); proof[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): self.dispatch([proof])
        proof = copy.deepcopy(self.proof); proof['row']['raw_sha256'] = '0' * 64
        with self.assertRaises(ValueError): self.dispatch([proof])

    def test_wrong_order_entry_spec_evidence_and_interruption_rejected(self):
        calls = [(Path('/other/evidence'), self.entries[0], self.spec, self.campaign['started_monotonic_ns'], False),
            (self.fixture.runs, dict(self.entries[0], job_index=1), self.spec, self.campaign['started_monotonic_ns'], False),
            (self.fixture.runs, self.entries[0], dict(self.spec, selected_case_target=100), self.campaign['started_monotonic_ns'], False),
            (self.fixture.runs, self.entries[0], self.spec, 0, False),
            (self.fixture.runs, self.entries[0], self.spec, self.campaign['started_monotonic_ns'], True)]
        for call in calls:
            with self.assertRaises(ValueError): self.dispatch()(*call)

    def test_candidate_integer_keys_round_trip_preserves_external_review_logic(self):
        # A synthetic review-logic fixture; no GPU or hardware evidence exists.
        row = {'run_id': 'synthetic-review-only', 'gpu_executed': True, 'raw_sha256': 'a' * 64,
            'counts': {'FAIL': 1}, 'candidate_failures': 1,
            '_candidate_records': {0: {'case_index': 0, 'run_id': 'synthetic-review-only', 'verdict': 'FAIL'}}}
        restored = adapter.decode_row(json.loads(adapter.canonical(adapter.encode_row(row))))
        self.assertEqual(restored, row)
        self.assertEqual(list(restored['_candidate_records']), [0])
        path = self.fixture.directory / 'synthetic-reviews.json'
        for state in ('INCONCLUSIVE', 'REJECTED'):
            path.write_bytes(adapter.canonical([{'run_id': row['run_id'], 'case_index': 0,
                'original_raw_sha256': row['raw_sha256'], 'review_state': state,
                'reviewer_identity': 'synthetic-unit-reviewer', 'rationale': 'Review logic fixture only',
                'reviewed_utc': '2026-10-10T07:00:00Z'}]))
            self.assertEqual(self.module.audit_reviews(path, [restored]), self.module.audit_reviews(path, [row]))
        encoded = adapter.encode_row(row)
        for pairs in ([encoded['_candidate_records'][0]] * 2,
                [{'case_index': '0', 'record': row['_candidate_records'][0]}],
                [{'case_index': 1, 'record': row['_candidate_records'][0]}]):
            with self.assertRaises(ValueError): adapter.decode_row(dict(encoded, _candidate_records=pairs))

    def test_deallocation_gate_requires_same_campaign_original_and_later_stop(self):
        archive, collection = self.fixture.archive(cpu=True)
        release = self.fixture.directory / 'release.json'
        campaign = dict(self.campaign, finished_utc='2026-10-10T07:00:00Z')
        release.write_bytes(adapter.canonical({'timestamp_utc': '2026-10-10T07:01:00Z', 'power_state': 'PowerState/deallocated'}))
        bound_identity, bound_sha = adapter.validate_deallocation_receipt(self.module, campaign, archive, collection, release)
        self.assertEqual(bound_sha, adapter.sha(release))
        self.assertEqual(bound_identity, adapter.identity(release))
        with self.assertRaises(ValueError): adapter.validate_deallocation_receipt(self.module, campaign, archive, collection, None)
        for value in ({'timestamp_utc': '2026-10-10T07:01:00Z', 'power_state': 'PowerState/running'},
                {'timestamp_utc': '2026-10-10T06:59:00Z', 'power_state': 'PowerState/deallocated'}):
            release.chmod(0o600);release.write_bytes(adapter.canonical(value))
            with self.assertRaises(ValueError): adapter.validate_deallocation_receipt(self.module, campaign, archive, collection, release)
        other = self.fixture.directory / 'other-release.json'
        other.write_bytes(adapter.canonical({'timestamp_utc': '2026-10-10T07:01:00Z', 'power_state': 'PowerState/deallocated'}))
        with self.assertRaises(ValueError): adapter.validate_deallocation_receipt(self.module, campaign, archive, collection, other)

    def test_metadata_preflight_rejects_oversized_header_before_reading(self):
        archive, _ = self.fixture.archive(cpu=True)
        import tarfile
        member = tarfile.TarInfo('evidence/runs/spec.json');member.size = self.module.METADATA_LIMIT + 1
        class HeaderOnly:
            def __enter__(self): return iter([member])
            def __exit__(self, *args): return False
        with patch.object(adapter.tarfile, 'open', return_value=HeaderOnly()):
            with self.assertRaisesRegex(ValueError, 'retained metadata volume'):
                adapter.preflight_archive_limits(self.module, archive, True)

    def test_changed_adapter_since_import_is_rejected(self):
        archive, collection = self.fixture.archive(cpu=True)
        with patch.object(adapter, 'IMPORTED_ADAPTER_SHA256', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'adapter changed since import'):
                self.run_adapter(archive, collection)
        self.assertFalse(self.output.exists())

    def test_actual_partial_cpu_archive_matches_original_serial_result_and_extracts_no_raw(self):
        archive, collection = self.fixture.archive(cpu=True)
        evidence = self.module.ArchiveEvidence(archive, collection, True)
        try:
            serial = self.module.analyze(evidence)
            serial.update(original_archive_sha256=adapter.sha(archive), original_collection_receipt_sha256=adapter.sha(collection),
                original_files_verified=evidence.verified_original_file_count, raw_archive_extraction_performed=False,
                original_host_hash_manifest_verified=evidence.original_host_hash_manifest_verified, cpu_qualification_archive_adapter=True)
        finally: evidence.close()
        before = adapter.sha(archive)
        result = self.run_adapter(archive, collection)
        self.assertEqual(result, serial)
        self.assertEqual(self.output.read_bytes(), adapter.canonical(serial))
        self.assertEqual(adapter.sha(archive), before)
        self.assertFalse(result['gpu_executed'])
        self.assertEqual(result['state'], 'PARTIAL_FIXED_WORK_AUDIT')
        self.assertFalse(list(self.output.with_name('parallel-audit-workers').rglob('records.jsonl')))
        receipt = adapter.read_proof(self.output.with_name('parallel-audit-parallel-receipt.json'))
        self.assertEqual(receipt['state'], 'VERIFIED_COMPOSED_OFFLINE_CPU_AUDIT')
        self.assertFalse(receipt['gpu_jobs_parallel'])
        self.assertEqual(receipt['scope'], 'CPU_ARCHIVE_QUALIFICATION_ONLY_NO_GPU_EXECUTION')
        self.assertFalse(receipt['gpu_compute_performed_by_adapter'])
        self.assertFalse(receipt['deallocation_gate_verified'])

    def test_semantic_payload_corruption_with_rehashed_originals_is_rejected(self):
        raw = self.fixture.runs / self.entries[0]['raw_file']
        record = json.loads(raw.read_bytes())
        record['observations'][0]['expected']['values'][0] += 1
        record['observations'][0]['observed']['values'][0] += 1
        self.fixture.write(raw, record)
        self.fixture.rehash_job()
        archive, collection = self.fixture.archive(cpu=True)
        before = adapter.sha(archive)
        with self.assertRaisesRegex(ValueError, 'independent deferred model'):
            self.run_adapter(archive, collection)
        self.assertFalse(self.output.exists())
        self.assertEqual(adapter.sha(archive), before)
        self.assertEqual(adapter.read_proof(self.output.with_name('parallel-audit-parallel-receipt.json'))['state'], 'FAILED_COMPOSED_OFFLINE_CPU_AUDIT')

    def test_source_hash_change_and_existing_output_rejected(self):
        archive, collection = self.fixture.archive(cpu=True)
        with self.assertRaisesRegex(ValueError, 'Analyzer changed'):
            adapter.parallel_analyze(self.module, ROOT, archive, collection, self.output, '0' * 64,
                cpu_qualification=True)
        self.output.write_text('existing original')
        with self.assertRaisesRegex(ValueError, 'existing output'):
            self.run_adapter(archive, collection)
        self.assertEqual(self.output.read_text(), 'existing original')

    def test_worker_error_fails_without_result_or_original_mutation(self):
        archive, collection = self.fixture.archive(cpu=True)
        before = adapter.sha(archive)
        class FailedPool:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def submit(self, *args):
                future = concurrent.futures.Future()
                future.set_exception(RuntimeError('CPU worker failure fixture'))
                return future
        with patch.object(adapter.concurrent.futures, 'ProcessPoolExecutor', return_value=FailedPool()):
            with self.assertRaisesRegex(RuntimeError, 'CPU worker failure fixture'):
                self.run_adapter(archive, collection)
        self.assertFalse(self.output.exists())
        self.assertEqual(adapter.sha(archive), before)
        self.assertEqual(adapter.read_proof(self.output.with_name('parallel-audit-parallel-receipt.json'))['state'], 'FAILED_COMPOSED_OFFLINE_CPU_AUDIT')


if __name__ == '__main__':
    unittest.main()
