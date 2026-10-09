import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from cc_contract.cli import canonical
from cc_contract.native import InfrastructureFailure
from cc_contract.runner import campaign
from cc_contract.search import METHODS


ROOT = Path(__file__).resolve().parents[2]


def load(name, filename):
    loader = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


harness = load('fixed_work_test_harness', 'run-fixed-work-campaign.py')
analysis = load('fixed_work_test_analysis', 'analyze-fixed-work-campaign.py')


class FixedWorkAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.template = Path(cls.fixture.name) / 'runs'
        cls.spec = harness.make_spec('model', 1, 120, analysis.SOURCE)
        calls = 0

        def first_job_only(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise InfrastructureFailure('Synthetic CPU fixture ends after the first job')
            return campaign(*args, **kwargs)

        with patch('cc_contract.runner.provenance', return_value=(analysis.SOURCE, False)):
            cls.receipt = harness.execute_campaign(cls.spec, canonical(cls.spec), cls.template,
                                                   campaign_function=first_job_only)
        if len(cls.receipt['jobs']) != 1:
            raise AssertionError('Expected one actual CPU job in partial fixture')

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.runs = self.directory / 'runs'
        shutil.copytree(self.template, self.runs)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, path, value):
        path.chmod(0o600)
        path.write_bytes(canonical(value))

    def rehash_job(self):
        receipt = analysis.metadata(self.runs / 'receipt.json')
        entry = receipt['jobs'][0]
        manifest_path = self.runs / entry['manifest_file']
        manifest = analysis.metadata(manifest_path)
        raw = self.runs / entry['raw_file']
        entry['raw_sha256'] = manifest['raw_sha256'] = analysis.sha(raw)
        entry['diagnostics']['raw_trace_bytes'] = raw.stat().st_size
        receipt['actual_total_trace_bytes'] = raw.stat().st_size
        self.write(manifest_path, manifest)
        for artifact in entry['artifacts']:
            file = self.runs / artifact['file']
            artifact.update(sha256=analysis.sha(file), bytes=file.stat().st_size)
        journal = [json.loads(line) for line in (self.runs / 'journal.jsonl').read_bytes().splitlines()]
        for event in journal:
            if event['event'] == 'job_finish' and event['job_index'] == 0:
                event.update(copy.deepcopy(entry))
        path = self.runs / 'journal.jsonl'
        path.chmod(0o600)
        path.write_bytes(b''.join(canonical(event) for event in journal))
        receipt['journal_sha256'] = analysis.sha(path)
        self.write(self.runs / 'receipt.json', receipt)

    def archive(self, extra=None, cpu=False):
        evidence = self.directory / ('evidence' if cpu else 'cc-contract-evidence')
        shutil.copytree(self.runs, evidence / 'fixed-work/runs')
        inputs = evidence / 'fixed-work-inputs'
        inputs.mkdir()
        for source in (ROOT / 'scripts/run-fixed-work-campaign.py', ROOT / 'scripts/run-work-sample.py',
                       ROOT / 'docs/methodology/fixed-work-campaign-v0.3.md', ROOT / 'experiments/comparison-schedule.json'):
            shutil.copyfile(source, inputs / source.name)
        listing = [analysis.sha(file) + '  ./' + file.relative_to(evidence).as_posix() + '\n'
                   for file in sorted(evidence.rglob('*')) if file.is_file()]
        if not cpu:
            (evidence / 'SHA256SUMS').write_text(''.join(listing))
        archive = self.directory / 'original.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            output.add(evidence, arcname=evidence.name)
            if extra is not None:
                output.addfile(extra)
        collection = self.directory / 'collection.json'
        collection.write_bytes(canonical({'archive_file': archive.name, 'archive_sha256': analysis.sha(archive), 'files_verified': len(listing)}))
        return archive, collection

    def test_real_partial_cpu_fixture_is_not_gpu_evidence(self):
        result = analysis.analyze(self.runs)
        self.assertEqual(result['state'], 'PARTIAL_FIXED_WORK_AUDIT')
        self.assertFalse(result['gpu_executed'])
        self.assertFalse(result['full_gpu_quota_matrix'])
        self.assertFalse(result['summaries']['available'])
        self.assertEqual(result['audited_jobs'], 1)
        self.assertEqual(len(result['missing_jobs']), 139)
        self.assertTrue(result['job_rows'][0]['censored'])
        self.assertIsNone(result['job_rows'][0]['time_to_detection'])
        self.assertEqual(result['job_rows'][0]['original_campaign_state'], 'COMPLETE_CASE_LIMIT_LOCAL_ONLY')

    def test_tar_stream_matches_folder_and_extracts_no_raw_files(self):
        original = analysis.analyze(self.runs)
        archive, collection = self.archive()
        before = {file.relative_to(self.directory) for file in self.directory.rglob('*')}
        evidence = analysis.ArchiveEvidence(archive, collection)
        try:
            result = analysis.analyze(evidence)
        finally:
            evidence.close()
        self.assertEqual(result, original)
        self.assertEqual(before, {file.relative_to(self.directory) for file in self.directory.rglob('*')})

    def test_raw_corruption_is_rejected(self):
        raw = self.runs / self.receipt['jobs'][0]['raw_file']
        raw.chmod(0o600)
        raw.write_bytes(raw.read_bytes() + b'{}\n')
        with self.assertRaises((ValueError, KeyError)):
            analysis.analyze(self.runs)

    def test_explicit_cpu_archive_adapter_preserves_original_receipt(self):
        archive, collection = self.archive(cpu=True)
        original_receipt_sha = analysis.sha(self.runs / 'receipt.json')
        evidence = analysis.ArchiveEvidence(archive, collection, cpu_qualification=True)
        try:
            result = analysis.analyze(evidence)
        finally:
            evidence.close()
        self.assertEqual(result['receipt_sha256'], original_receipt_sha)
        self.assertFalse(result['gpu_executed'])
        self.assertFalse(evidence.original_host_hash_manifest_verified)
        self.assertFalse(result['summaries']['available'])

    def test_cpu_archive_adapter_cannot_accept_gpu_receipt(self):
        receipt = analysis.metadata(self.runs / 'receipt.json')
        receipt['gpu_executed'] = True
        self.write(self.runs / 'receipt.json', receipt)
        archive, collection = self.archive(cpu=True)
        with self.assertRaisesRegex(ValueError, 'cannot become GPU evidence'):
            analysis.ArchiveEvidence(archive, collection, cpu_qualification=True)

    def test_semantic_corruption_rejected_after_recomputing_all_hashes(self):
        raw = self.runs / self.receipt['jobs'][0]['raw_file']
        record = json.loads(raw.read_bytes())
        self.assertEqual(record['verdict'], 'PASS')
        record['observations'][0]['expected']['values'][0] += 1
        record['observations'][0]['observed']['values'][0] += 1
        self.write(raw, record)
        self.rehash_job()
        with self.assertRaisesRegex(ValueError, 'independent deferred model'):
            analysis.analyze(self.runs)

    def test_cpu_scope_cannot_be_promoted_to_gpu_in_receipt(self):
        receipt = analysis.metadata(self.runs / 'receipt.json')
        receipt['gpu_executed'] = True
        self.write(self.runs / 'receipt.json', receipt)
        with self.assertRaisesRegex(ValueError, 'execution scope'):
            analysis.analyze(self.runs)

    def test_missing_job_cannot_be_labelled_complete(self):
        receipt = analysis.metadata(self.runs / 'receipt.json')
        receipt['state'] = 'COMPLETE_FIXED_WORK_CAMPAIGN'
        receipt['error'] = None
        self.write(self.runs / 'receipt.json', receipt)
        with self.assertRaisesRegex(ValueError, 'labelled partial'):
            analysis.analyze(self.runs)

    def test_legacy_budget_state_does_not_satisfy_case_quota(self):
        receipt = analysis.metadata(self.runs / 'receipt.json')
        receipt['jobs'][0]['fixed_work_completion'] = False
        self.write(self.runs / 'receipt.json', receipt)
        self.rehash_job()
        with self.assertRaisesRegex(ValueError, 'completion contradicts'):
            analysis.analyze(self.runs)

    def test_unlisted_partial_originals_are_reported(self):
        extra = self.runs / 'campaign-abandoned'
        extra.mkdir()
        (extra / 'records.jsonl').write_bytes(b'{}\n')
        result = analysis.analyze(self.runs)
        self.assertEqual(result['unlisted_partial_original_files'], ['campaign-abandoned/records.jsonl'])
        self.assertFalse(result['all_case_traces_independently_recomputed'])

    def test_progress_metrics_rejected_after_receipt_and_journal_rehash(self):
        receipt = analysis.metadata(self.runs / 'receipt.json')
        receipt['jobs'][0]['diagnostics']['progress_quartiles'][0]['coverage']['structural'] += 1
        self.write(self.runs / 'receipt.json', receipt)
        self.rehash_job()
        with self.assertRaisesRegex(ValueError, 'Progress metrics'):
            analysis.analyze(self.runs)

    def test_development_partition_rejected(self):
        spec = analysis.metadata(self.runs / 'spec.json')
        spec['partition'] = 'development_finite_work_time_pilot'
        self.write(self.runs / 'spec.json', spec)
        with self.assertRaisesRegex(ValueError, 'Development'):
            analysis.analyze(self.runs)

    def test_malicious_tar_member_rejected(self):
        archive, collection = self.archive(tarfile.TarInfo('../escape'))
        with self.assertRaisesRegex(ValueError, 'Unsafe archive path'):
            analysis.ArchiveEvidence(archive, collection)

    def test_full_summaries_require_every_gpu_quota(self):
        with self.assertRaisesRegex(ValueError, 'every declared quota'):
            analysis.summarize([], True, True)
        self.assertFalse(analysis.summarize([], False, True)['available'])

    def test_inconclusive_external_review_does_not_resolve_candidate(self):
        # Synthetic review logic fixture, not an executed GPU experiment.
        rows = [{'run_id': 'synthetic-only', 'gpu_executed': True, 'raw_sha256': 'a' * 64,
                 '_candidate_records': {0: {'verdict': 'FAIL'}}}]
        path = self.directory / 'reviews.json'
        path.write_bytes(canonical([{'run_id': 'synthetic-only', 'case_index': 0,
                                     'original_raw_sha256': 'a' * 64, 'review_state': 'INCONCLUSIVE',
                                     'reviewer_identity': 'synthetic unit-test reviewer',
                                     'rationale': 'No mechanism established', 'reviewed_utc': '2026-10-09T21:00:00+00:00'}]))
        self.assertEqual(analysis.audit_reviews(path, rows), set())

    def test_confirmed_defect_requires_two_fresh_replays(self):
        rows = [{'run_id': 'synthetic-only', 'gpu_executed': True, 'raw_sha256': 'a' * 64,
                 '_candidate_records': {0: {'verdict': 'FAIL'}}}]
        path = self.directory / 'reviews.json'
        path.write_bytes(canonical([{'run_id': 'synthetic-only', 'case_index': 0,
                                     'original_raw_sha256': 'a' * 64, 'review_state': 'CONFIRMED',
                                     'reviewer_identity': 'synthetic unit-test reviewer', 'rationale': 'Fixture only',
                                     'reviewed_utc': '2026-10-09T21:00:00+00:00', 'defect_id': 'unit-test-only',
                                     'characterized_mechanism': 'Synthetic test', 'reproductions': []}]))
        with self.assertRaisesRegex(ValueError, 'Two fresh process'):
            analysis.audit_reviews(path, rows)

    def test_paired_block_statistics_do_not_treat_cases_as_replicates(self):
        rows = []
        for block in range(20):
            for method in METHODS:
                rows.append({'block': block, 'method': method, 'gpu_executed': True, 'fixed_work_complete': True,
                             'selected_cases': 100, 'candidate_draws': 100 if method in ('B1', 'B2') else 1600,
                             'valid_selected_fraction': .9 if method == 'B4' else .8,
                             'coverage': {'structural': 10 if method == 'B4' else 8, 'temporal': 20},
                             'actual_job_seconds': 2, 'confirmed_defects': 0, 'detected': False})
        result = analysis.summarize(rows, True, True)
        comparison = result['paired_comparisons']['B1']
        self.assertEqual(comparison['independent_paired_blocks'], 20)
        self.assertEqual(result['bootstrap'], {'seed': 59001, 'resamples': 5000})
        self.assertEqual(comparison['metrics']['structural_coverage']['paired_block_bootstrap_95_percentile_ci'], [2., 2.])
        self.assertEqual(comparison['holm_adjusted_primary_detection_p'], 1.)
        self.assertFalse(result['superiority_established'])
        self.assertFalse(result['case_count_scientific_adequacy_established'])


if __name__ == '__main__':
    unittest.main()
