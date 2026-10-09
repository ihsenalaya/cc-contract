"""Corruption tests for the local gate chain; every workload here is a CPU fixture."""
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from cc_contract.cli import canonical
from cc_contract.generators import generate
from cc_contract.model import execute
from cc_contract.runner import ModelExecutor

ROOT = Path(__file__).resolve().parents[2]


def import_script(path, name):
    loader = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(result)
    return result


prep = import_script(ROOT / 'scripts/prepare-fixed-work-campaign.py', 'fixed_work_bundle')
fixed = import_script(ROOT / 'scripts/run-fixed-work-campaign.py', 'fixed_work_bundle_fixture_runner')
qualifier = import_script(ROOT / 'scripts/qualify-fixed-work-campaign.py', 'fixed_work_bundle_fixture_inventory')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


class FixedWorkBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.originals = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.originals.cleanup)
        cls.fixture = Path(cls.originals.name)
        case = generate(9, 'T01', size=2)
        class FixturePolicy:
            def __init__(self, *_):
                self.draws, self.structural, self.temporal = 0, set(), set()
                self.rng = random.Random(9)
            def next(self):
                self.draws += 1
                return case
            def observe(self, _):
                self.structural.add('CPU_UNIT_FIXTURE')
        class FixtureWorker(ModelExecutor):
            environment = {'scope': 'CPU_NATIVE_REFERENCE_ONLY', 'gpu_executed': False,
                           'unit_fixture': True, 'hardware_attestation': 'NOT_RUN'}
            def execute(self, scenario):
                observations = execute(scenario)
                for observation in observations:
                    observation.update(scope='CPU_NATIVE_REFERENCE_ONLY', gpu_executed=False)
                return observations
        with patch.dict(os.environ, {'CC_IMAGE_DIGEST': fixed.IMAGE_DIGEST}), \
                patch('cc_contract.runner.provenance', return_value=(fixed.SOURCE_COMMIT, False)), \
                patch('cc_contract.runner.Search', FixturePolicy):
            cls.cpu_spec = fixed.make_spec('native-reference', 4, source_commit=fixed.SOURCE_COMMIT)
            cls.cpu_bytes = canonical(cls.cpu_spec)
            cls.cpu_receipt = fixed.execute_campaign(cls.cpu_spec, cls.cpu_bytes, cls.fixture / 'evidence/runs',
                                                    lambda _: FixtureWorker())
        (cls.fixture / 'evidence/harness.stdout').write_bytes(b'CPU UNIT FIXTURE ONLY\n')
        (cls.fixture / 'evidence/harness.stderr').write_bytes(b'')
        cls.archive = cls.fixture / 'worker.tar.gz'
        with tarfile.open(cls.archive, 'w:gz') as archive:
            archive.add(cls.fixture / 'evidence', arcname='evidence')
        cls.inventory, _ = qualifier.archive_inventory(cls.archive)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(prep, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        for filename in ('run-fixed-work-campaign.py', 'run-work-sample.py',
                         'qualify-fixed-work-campaign.py', 'analyze-fixed-work-campaign.py',
                         'azure-window.py', 'qualify-host.sh', 'azure-resume-campaign.py'):
            path = self.root / 'scripts' / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / 'scripts' / filename, path)
        for filename in (fixed.PROTOCOL_FILE, fixed.RESERVED_SCHEDULE_FILE,
                         'experiments/fixed-work-campaign-spec.json'):
            path = self.root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / filename, path)
        self.spec_path = self.root / 'experiments/fixed-work-campaign-spec.json'
        self.spec = json.loads(self.spec_path.read_bytes())
        for name, image, source in (('cuda', prep.CUDA_IMAGE, prep.CUDA_SOURCE),
                                    ('ir', fixed.IMAGE_DIGEST, fixed.SOURCE_COMMIT)):
            directory = self.root / '.local' / name
            original = directory / 'qualified-fixture'
            original.mkdir(parents=True)
            proof = original / 'cpu-proof.log'
            proof.write_bytes(b'CPU IMAGE QUALIFICATION UNIT FIXTURE ONLY\n')
            gate = {'verified': True, 'image_id': image.split('@')[1], 'git_commit': source,
                    'scope': 'CPU_REFERENCE_AND_NO_GPU_REJECTION_ONLY', 'workers': list(prep.NODES),
                    'hashes': {'cpu-proof.log': prep.sha(proof)}}
            if name == 'ir':
                gate['cases_per_worker'] = 96
            write(directory / 'kind-verified.json', gate)
            write(original / 'verified.json', gate)
            write(directory / 'inspect.json', [{'Id': gate['image_id'], 'Config': {'Labels': {
                'org.opencontainers.image.revision': source}}}])
            write(directory / 'registry.json', {'digest': image.split('@')[1]})
            (directory / 'remote-digest').write_text(image + '\n')
        self.kind_directory = self.root / 'kind'
        self.kind_directory.mkdir()
        (self.kind_directory / 'spec.json').write_bytes(self.cpu_bytes)
        workers, reviewed = [], []
        for index, node in enumerate(prep.NODES):
            archive = self.kind_directory / ('worker-' + str(index) + '.tar.gz')
            shutil.copyfile(self.archive, archive)
            write(self.kind_directory / ('artifact-inventory-' + str(index) + '.json'), self.inventory)
            (self.kind_directory / ('pod-' + str(index) + '.stdout')).write_bytes(base64.b64encode(archive.read_bytes()))
            (self.kind_directory / ('pod-' + str(index) + '.stderr')).write_bytes(b'')
            workers.append({'node': node, 'index': index, 'phase': 'Succeeded', 'exported': True,
                'archive_sha256': prep.sha(archive), 'archive_bytes': archive.stat().st_size,
                'stdout_sha256': prep.sha(self.kind_directory / ('pod-' + str(index) + '.stdout')),
                'stderr_sha256': prep.sha(self.kind_directory / ('pod-' + str(index) + '.stderr')),
                'completed_jobs': 140, 'finite_work_completed_jobs': 140, 'selected_cases_per_job': 4,
                'selected_cases': 560, 'gpu_executed': False, 'artifact_inventory_sha256':
                    prep.sha(self.kind_directory / ('artifact-inventory-' + str(index) + '.json'))})
            individual = {'state': 'PASS_CPU_FIXED_WORK_DIAGNOSTIC_AUDIT', 'gpu_executed': False,
                'full_gpu_quota_matrix': False, 'audited_jobs': 140, 'audited_selected_cases': 560,
                'spec_sha256': hashlib.sha256(self.cpu_bytes).hexdigest(),
                'receipt_sha256': self.inventory['evidence/runs/receipt.json']['sha256'],
                'harness_sha256': self.spec['harness_sha256'], 'shared_harness_sha256': self.spec['shared_harness_sha256'],
                'protocol_sha256': self.spec['protocol_sha256'], 'reserved_schedule_sha256': self.spec['reserved_schedule_sha256'],
                'all_case_traces_independently_recomputed': True, 'raw_files_modified': False,
                'candidate_failures': 0, 'missing_jobs': [], 'partial_jobs': [], 'job_rows': []}
            for job in self.cpu_receipt['jobs']:
                individual['job_rows'].append({'run_id': job['run_id'], 'raw_sha256': job['raw_sha256'],
                    'block': job['configuration']['block'], 'method': job['configuration']['method'],
                    'seed': job['configuration']['seed'], 'fixed_work_complete': True, 'gpu_executed': False,
                    'scope': 'CPU_NATIVE_REFERENCE_ONLY', 'selected_cases': 4, 'selected_case_target': 4})
            audit = self.kind_directory / ('audit-' + str(index) + '.json')
            write(audit, individual)
            reviewed.append({'worker': node, 'archive_file': str(archive), 'archive_sha256': prep.sha(archive),
                'archive_bytes': archive.stat().st_size, 'audit_file': str(audit), 'audit_sha256': prep.sha(audit),
                'audited_jobs': 140, 'audited_selected_cases': 560, 'selected_case_target': 4,
                'backend': 'native-reference', 'scope': 'CPU_NATIVE_REFERENCE_ONLY'})
        kind = {'scope': 'CPU_KIND_FIXED_WORK_CAMPAIGN_FUNCTIONAL_PIPELINE_ONLY', 'verified': True,
            'gpu_executed': False, 'image_digest': fixed.IMAGE_DIGEST, 'image_id': fixed.IMAGE_DIGEST.split('@')[1],
            'science_source_commit': fixed.SOURCE_COMMIT, 'harness_sha256': self.spec['harness_sha256'],
            'shared_harness_sha256': self.spec['shared_harness_sha256'], 'protocol_sha256': self.spec['protocol_sha256'],
            'reserved_schedule_sha256': self.spec['reserved_schedule_sha256'], 'spec_sha256': hashlib.sha256(self.cpu_bytes).hexdigest(),
            'qualifier_sha256': prep.sha(self.root / 'scripts/qualify-fixed-work-campaign.py'),
            'jobs_per_worker': 140, 'selected_cases_per_job': 4, 'total_selected_cases': 1120,
            'safety_timeout_seconds': 120, 'secret_access': 'DENIED', 'gpu_parallel_execution_tested': False,
            'new_images_built': 0, 'workers': workers}
        self.kind_path = self.kind_directory / 'verified.json'
        write(self.kind_path, kind)
        write(self.kind_directory / 'cleanup.json', {'namespace_deleted': 'CPU-UNIT-FIXTURE-ONLY', 'failure_type': None})
        review = {'state': prep.REVIEW_STATE, 'gpu_executed': False, 'harness_sha256': self.spec['harness_sha256'],
            'shared_harness_sha256': self.spec['shared_harness_sha256'], 'protocol_sha256': self.spec['protocol_sha256'],
            'reserved_schedule_sha256': self.spec['reserved_schedule_sha256'], 'gpu_spec_sha256': prep.sha(self.spec_path),
            'audited_jobs': 280, 'audited_selected_cases': 1120, 'all_original_payload_bytes_unchanged': True,
            'reviewer_sha256': prep.sha(self.root / 'scripts/analyze-fixed-work-campaign.py'), 'workers': reviewed}
        self.review_path = self.root / 'independent-review.json'
        write(self.review_path, review)
        log = self.root / 'local-check.log'
        log.write_bytes(b'CPU UNIT FIXTURE MOCKED LOCAL CHECKS ONLY\n')
        local = {'state': prep.LOCAL_STATE, 'scope': prep.LOCAL_SCOPE, 'gpu_executed': False,
            'spec_sha256': prep.sha(self.spec_path), 'harness_sha256': self.spec['harness_sha256'],
            'helper_harness_sha256': self.spec['shared_harness_sha256'], 'protocol_sha256': self.spec['protocol_sha256'],
            'reserved_schedule_sha256': self.spec['reserved_schedule_sha256'],
            'checks': {name: 'PASS' for name in prep.CHECKS}, 'cloud_controller_sha256': prep.sha(self.root / 'scripts/azure-window.py'),
            'host_script_sha256': prep.sha(self.root / 'scripts/qualify-host.sh'),
            'resume_controller_sha256': prep.sha(self.root / 'scripts/azure-resume-campaign.py'),
            'log_files': [{'path': str(log), 'bytes': log.stat().st_size, 'sha256': prep.sha(log)}]}
        self.local_path = self.root / 'local-qualification.json'
        write(self.local_path, local)

    def bundle(self):
        return prep.make_bundle(self.spec_path, self.root / fixed.PROTOCOL_FILE,
            self.root / fixed.RESERVED_SCHEDULE_FILE, self.kind_path, self.review_path, self.local_path)

    def test_end_to_end_original_fixture_chain_scoped_and_no_model_download(self):
        bundle = self.bundle()
        verified = prep.verify_local_gates(bundle)
        self.assertTrue(verified['verified'])
        self.assertFalse(verified['gpu_executed'])
        self.assertEqual(verified['cpu_selected_cases'], 1120)
        self.assertEqual(set(bundle['images']), {'cuda', 'ir'})
        self.assertFalse(bundle['model_download_required'])
        self.assertFalse(bundle['gpu_jobs_parallel'])
        self.assertEqual(bundle['planned_jobs'], 140)
        self.assertEqual(bundle['selected_cases_per_job'], 100)
        self.assertEqual(bundle['archive_download_byte_limit'], 8589934592)

    def test_original_archive_mutation_blocks_even_with_unchanged_receipts(self):
        bundle = self.bundle()
        with (self.kind_directory / 'worker-0.tar.gz').open('ab') as archive:
            archive.write(b'altered')
        with self.assertRaisesRegex(ValueError, 'Original CPU archive changed'):
            prep.verify_local_gates(bundle)

    def test_rehashed_independent_audit_cannot_refer_to_other_original_receipt(self):
        bundle = self.bundle()
        path = self.kind_directory / 'audit-0.json'
        data = json.loads(path.read_bytes()); data['receipt_sha256'] = '0' * 64; write(path, data)
        review = json.loads(self.review_path.read_bytes())
        review['workers'][0]['audit_sha256'] = prep.sha(path); write(self.review_path, review)
        bundle['independent_cpu_review_sha256'] = prep.sha(self.review_path)
        with self.assertRaisesRegex(ValueError, 'original receipt or source changed'):
            prep.verify_local_gates(bundle)

    def test_matching_hashes_do_not_allow_reduced_cpu_work_or_gpu_claim(self):
        bundle = self.bundle()
        for field, value in [('total_selected_cases', 112), ('gpu_executed', True), ('jobs_per_worker', 14)]:
            original = self.kind_path.read_bytes()
            data = json.loads(original); data[field] = value; write(self.kind_path, data)
            changed = {**bundle, 'cpu_kind_receipt_sha256': prep.sha(self.kind_path)}
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Both original native CPU'):
                prep.verify_local_gates(changed)
            self.kind_path.write_bytes(original)

    def test_infrastructure_source_and_original_log_changes_invalidate_gate(self):
        bundle = self.bundle()
        cloud = self.root / 'scripts/azure-window.py'
        cloud.write_bytes(cloud.read_bytes() + b'\n# changed after qualification\n')
        with self.assertRaisesRegex(ValueError, 'infrastructure source changed'):
            prep.verify_local_gates(bundle)
        cloud.write_bytes((ROOT / 'scripts/azure-window.py').read_bytes())
        (self.root / 'local-check.log').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'qualification log changed'):
            prep.verify_local_gates(bundle)

    def test_qualified_image_originals_and_helper_are_rechecked(self):
        bundle = self.bundle()
        proof = self.root / '.local/ir/qualified-fixture/cpu-proof.log'
        proof.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'image qualification artifact changed'):
            prep.verify_local_gates(bundle)
        proof.write_bytes(b'CPU IMAGE QUALIFICATION UNIT FIXTURE ONLY\n')
        helper = self.root / 'scripts/run-work-sample.py'
        helper.write_bytes(helper.read_bytes() + b'\n# changed\n')
        with self.assertRaisesRegex(ValueError, 'immutable hash'):
            prep.verify_local_gates(bundle)

    def test_bundle_scope_rejects_torch_parallel_archive_or_quota_changes(self):
        bundle = self.bundle()
        for field, value in [('gpu_jobs_parallel', True), ('selected_cases_per_job', 99),
                             ('archive_download_byte_limit', 99999999999), ('campaign_id', 'other')]:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'scope or guards changed'):
                prep.verify_local_gates({**bundle, field: value})
        changed = copy.deepcopy(bundle)
        changed['images']['torch'] = fixed.IMAGE_DIGEST
        with self.assertRaisesRegex(ValueError, 'only the original qualified CUDA and IR'):
            prep.verify_local_gates(changed)


if __name__ == '__main__':
    unittest.main()
