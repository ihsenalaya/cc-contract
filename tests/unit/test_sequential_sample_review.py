"""CPU fixtures check archive audit rejection paths, never GPU qualification."""
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


ROOT = Path(__file__).resolve().parents[2]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


harness = module('sample_harness_review_fixture', 'run-sequential-sample.py')
reviewer = module('sample_reviewer', 'review-sequential-sample.py')


class SequentialSampleReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.template = Path(cls.fixture.name)
        evidence = cls.template / 'cc-contract-evidence'
        inputs = evidence / 'sample-inputs'
        inputs.mkdir(parents=True)
        cls.spec = harness.make_spec('model', .001, reviewer.SOURCE)
        payload = canonical(cls.spec)
        (inputs / 'spec.json').write_bytes(payload)
        shutil.copyfile(ROOT / 'scripts/run-sequential-sample.py', inputs / 'run-sequential-sample.py')
        # This synthetic CPU fixture records a fixed source identity so that
        # running tests in an edited checkout cannot masquerade as dirty GPU work.
        with patch('cc_contract.runner.provenance', return_value=(reviewer.SOURCE, False)):
            receipt = harness.execute_sample(cls.spec, payload, evidence / 'sequential-sample/runs')
        if receipt['state'] != 'COMPLETE_SAMPLE':
            raise AssertionError('CPU archive fixture did not finish: ' + receipt['state'])
        (cls.template / 'workload-bundle.json').write_bytes(canonical({
            'transport': 'SEQUENTIAL_IR_SAMPLE', 'images': {'ir': reviewer.IMAGE},
            'sample_spec_sha256': hashlib.sha256(payload).hexdigest(),
            'sample_harness_sha256': cls.spec['harness_sha256']}))

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        shutil.copytree(self.template, self.directory, dirs_exist_ok=True)
        self.evidence = self.directory / 'cc-contract-evidence'
        self.runs = self.evidence / 'sequential-sample/runs'

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, data):
        path.chmod(0o600)
        path.write_bytes(data)

    def archive(self, extra=None):
        listing = []
        for path in sorted(self.evidence.rglob('*')):
            if path.is_file() and path.name != 'SHA256SUMS':
                listing.append(reviewer.sha(path) + '  ./' + path.relative_to(self.evidence).as_posix() + '\n')
        (self.evidence / 'SHA256SUMS').write_text(''.join(listing))
        archive = self.directory / 'original.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            output.add(self.evidence, arcname='cc-contract-evidence')
            if extra:
                output.addfile(extra)
        (self.directory / 'collection.json').write_bytes(canonical({
            'archive_file': archive.name, 'archive_sha256': reviewer.sha(archive),
            'files_verified': len(listing)}))
        return reviewer.review(self.directory)

    def resave_job(self, receipt, entry):
        for artifact in entry['artifacts']:
            path = self.runs / artifact['file']
            artifact.update(sha256=reviewer.sha(path), bytes=path.stat().st_size)
        journal = [json.loads(line) for line in (self.runs / 'journal.jsonl').read_bytes().splitlines()]
        for event in journal:
            if event['event'] == 'job_finish' and event['job_index'] == entry['job_index']:
                event.update(copy.deepcopy(entry))
        data = b''.join(canonical(event) for event in journal)
        self.write(self.runs / 'journal.jsonl', data)
        receipt['journal_sha256'] = hashlib.sha256(data).hexdigest()
        self.write(self.runs / 'receipt.json', canonical(receipt))

    def test_cpu_sample_is_not_gpu_evidence(self):
        result = self.archive()
        self.assertEqual(result['state'], 'PASS_CPU_DIAGNOSTIC_AUDIT')
        self.assertFalse(result['gpu_executed'])
        self.assertEqual(result['audited_jobs'], 14)
        self.assertTrue(result['all_case_traces_independently_recomputed'])
        self.assertTrue(all(row['gpu_passing_cases_per_second'] is None for row in result['jobs']))
        self.assertFalse(result['establishes_shorter_comparative_budget'])

    def test_semantic_tampering_is_rejected_even_after_all_hashes_are_recomputed(self):
        receipt = json.loads((self.runs / 'receipt.json').read_text())
        for entry in receipt['jobs']:
            path = self.runs / entry['raw_file']
            rows = [json.loads(line) for line in path.read_bytes().splitlines()]
            selected = next((row for row in rows if row['verdict'] == 'PASS'), None)
            if selected is not None:
                # Self-consistent reported expected/observed/verdict still
                # contradict the actual frozen operation sequence.
                selected['observations'][0]['expected']['values'][0] += 1
                selected['observations'][0]['observed']['values'][0] += 1
                data = b''.join(canonical(row) for row in rows)
                self.write(path, data)
                entry['raw_sha256'] = hashlib.sha256(data).hexdigest()
                manifest_path = self.runs / entry['manifest_file']
                manifest = json.loads(manifest_path.read_text())
                manifest['raw_sha256'] = entry['raw_sha256']
                self.write(manifest_path, canonical(manifest))
                self.resave_job(receipt, entry)
                break
        else:
            self.fail('Fixture has no passing case to mutate')
        with self.assertRaisesRegex(ValueError, 'independent deferred model'):
            self.archive()

    def test_overlapping_sequential_intervals_are_rejected(self):
        path = self.runs / 'receipt.json'
        receipt = json.loads(path.read_text())
        receipt['jobs'][1]['started_monotonic_ns'] = receipt['jobs'][0]['finished_monotonic_ns'] - 1
        self.write(path, canonical(receipt))
        with self.assertRaisesRegex(ValueError, 'intervals overlap'):
            self.archive()

    def test_changed_campaign_source_is_rejected(self):
        receipt = json.loads((self.runs / 'receipt.json').read_text())
        entry = receipt['jobs'][0]
        for filename in ('start.json', 'manifest.json'):
            path = self.runs / entry['run_id'] / filename
            value = json.loads(path.read_text())
            value['git_commit'] = 'f' * 40
            self.write(path, canonical(value))
        self.resave_job(receipt, entry)
        with self.assertRaisesRegex(ValueError, 'image/source mismatch'):
            self.archive()

    def test_changed_harness_is_rejected(self):
        path = self.evidence / 'sample-inputs/run-sequential-sample.py'
        path.write_bytes(path.read_bytes() + b'\n# different source\n')
        with self.assertRaisesRegex(ValueError, 'harness hash differs'):
            self.archive()

    def test_missing_job_is_explicitly_partial_and_unlisted_original_is_preserved(self):
        receipt = json.loads((self.runs / 'receipt.json').read_text())
        omitted = receipt['jobs'].pop()
        receipt['completed_jobs'] = 13
        receipt['state'] = 'STOPPED_INTERRUPTED'
        journal = [json.loads(line) for line in (self.runs / 'journal.jsonl').read_bytes().splitlines()]
        journal = [event for event in journal if event.get('job_index') != omitted['job_index']]
        journal[-1].update(state='STOPPED_INTERRUPTED', completed_jobs=13)
        payload = b''.join(canonical(event) for event in journal)
        self.write(self.runs / 'journal.jsonl', payload)
        receipt['journal_sha256'] = hashlib.sha256(payload).hexdigest()
        self.write(self.runs / 'receipt.json', canonical(receipt))
        result = self.archive()
        self.assertEqual(result['state'], 'PARTIAL_SAMPLE_AUDIT')
        self.assertEqual(result['audited_jobs'], 13)
        self.assertFalse(result['all_case_traces_independently_recomputed'])
        self.assertEqual(result['unlisted_partial_trace_files'], [reviewer.PREFIX + omitted['raw_file']])
        self.assertFalse(result['establishes_statistical_superiority'])

    def test_unsafe_archive_member_is_rejected(self):
        unsafe = tarfile.TarInfo('cc-contract-evidence/../outside')
        with self.assertRaisesRegex(ValueError, 'Unsafe archive path'):
            self.archive(unsafe)


if __name__ == '__main__':
    unittest.main()
