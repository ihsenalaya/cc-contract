"""Bind verified CPU originals and local lifecycle checks to a fixed GPU plan.

This read-only preparation does not provision or start a VM. CPU qualification
does not establish CUDA execution, GPU attestation, or scientific adequacy.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
CAMPAIGN_ID = 'fixed-work-1010a'
CUDA_SOURCE = 'e8f34fddc62479a6995dcf260a4242e1494cc26b'
CUDA_IMAGE = 'ghcr.io/ihsenalaya/cc-contract-cuda@sha256:98eda97f53d3b77c9dee5629ab11e9484f644e7d7c38d57ffaa3feb6a4c74302'
NODES = ('cc-contract-worker', 'cc-contract-worker2')
LOCAL_STATE = 'PASS_LOCAL_FIXED_WORK_CAMPAIGN_QUALIFICATION'
LOCAL_SCOPE = 'CPU_AND_MOCKED_CLOUD_FIXED_WORK_CAMPAIGN_ONLY'
REVIEW_STATE = 'PASS_INDEPENDENT_CPU_FIXED_WORK_KIND_QUALIFICATION'
CHECKS = {'cloud_resume', 'stop_only', 'streaming_export', 'unit_review'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Missing or unsafe local proof: ' + str(path))
    require(path.stat().st_size <= 16 * 1024 * 1024, 'Oversized local proof metadata')
    return json.loads(path.read_bytes())


def module(filename, name):
    loader = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    result = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(result)
    return result


def bound_path(bundle, prefix):
    path = Path(bundle[prefix + '_path'])
    require(path.is_absolute() and path.is_file() and not path.is_symlink(), 'Missing or unsafe bound proof: ' + prefix)
    require(sha(path) == bundle[prefix + '_sha256'], 'Bound local proof changed: ' + prefix)
    return path


def qualified_images():
    fixed = module('run-fixed-work-campaign.py', 'fixed_bundle_image_bindings')
    images, gates = {}, {}
    for name, expected_image, expected_source in (
            ('cuda', CUDA_IMAGE, CUDA_SOURCE), ('ir', fixed.IMAGE_DIGEST, fixed.SOURCE_COMMIT)):
        directory = ROOT / '.local' / name
        gate_path, inspect_path = directory / 'kind-verified.json', directory / 'inspect.json'
        registry_path, digest_path = directory / 'registry.json', directory / 'remote-digest'
        gate, inspection, registry = load(gate_path), load(inspect_path)[0], load(registry_path)
        image = digest_path.read_text().strip()
        require(image == expected_image and image.split('@')[1] == registry['digest'], 'Pinned immutable image publication changed: ' + name)
        require(gate['verified'] is True and gate['image_id'] == inspection['Id'] and
                gate['git_commit'] == expected_source and
                inspection['Config']['Labels']['org.opencontainers.image.revision'] == expected_source and
                gate['scope'].startswith('CPU_') and set(gate['workers']) == set(NODES),
                'Existing image CPU qualification or source changed: ' + name)
        if name == 'ir':
            require(gate['cases_per_worker'] == 96, 'IR image qualification requires 96 cases per worker')
        originals = [path.parent for path in directory.glob('*/verified.json') if load(path) == gate]
        require(originals and isinstance(gate.get('hashes'), dict) and gate['hashes'], 'Original qualified image evidence missing: ' + name)
        proof_directory = originals[0]
        for filename, expected in gate['hashes'].items():
            require(Path(filename).name == filename and sha(proof_directory / filename) == expected,
                    'Original image qualification artifact changed: ' + name + '/' + filename)
        images[name] = image
        gates[name] = {'image_id': inspection['Id'], 'source_commit': expected_source,
                       'kind_gate_sha256': sha(gate_path), 'inspection_sha256': sha(inspect_path),
                       'registry_sha256': sha(registry_path), 'remote_digest_sha256': sha(digest_path),
                       'original_kind_evidence_directory': str(proof_directory.resolve()),
                       'scope': gate['scope']}
    return images, gates


def verify_kind(path, spec, fixed):
    kind = load(path)
    require(kind.get('scope') == 'CPU_KIND_FIXED_WORK_CAMPAIGN_FUNCTIONAL_PIPELINE_ONLY' and
            kind.get('verified') is True and kind.get('gpu_executed') is False and
            kind.get('image_digest') == fixed.IMAGE_DIGEST and kind.get('science_source_commit') == fixed.SOURCE_COMMIT and
            kind.get('harness_sha256') == spec['harness_sha256'] and
            kind.get('shared_harness_sha256') == spec['shared_harness_sha256'] and
            kind.get('protocol_sha256') == spec['protocol_sha256'] and
            kind.get('reserved_schedule_sha256') == spec['reserved_schedule_sha256'] and
            kind.get('jobs_per_worker') == 140 and kind.get('selected_cases_per_job') == 4 and
            kind.get('total_selected_cases') == 1120 and kind.get('safety_timeout_seconds') == 120 and
            kind.get('secret_access') == 'DENIED' and kind.get('gpu_parallel_execution_tested') is False and
            kind.get('new_images_built') == 0,
            'Both original native CPU Kind workers must qualify 140 jobs of four cases')
    qualifier_path = ROOT / 'scripts/qualify-fixed-work-campaign.py'
    require(kind.get('qualifier_sha256') == sha(qualifier_path), 'Kind qualifier source changed')
    require(len(kind.get('workers', [])) == 2 and [worker['node'] for worker in kind['workers']] == list(NODES),
            'Both declared CPU workers required in order')
    cpu_spec_path = path.parent / 'spec.json'
    cpu_bytes = cpu_spec_path.read_bytes()
    expected = fixed.make_spec('native-reference', 4, 120, source_commit=fixed.SOURCE_COMMIT)
    expected['image_digest'] = fixed.IMAGE_DIGEST
    require(sha(cpu_spec_path) == kind['spec_sha256'] and json.loads(cpu_bytes) == expected,
            'CPU specification differs from the final native-reference qualification')
    qualifier = module('qualify-fixed-work-campaign.py', 'fixed_bundle_cpu_original_review')
    verified = []
    for index, worker in enumerate(kind['workers']):
        require(worker.get('index') == index and worker.get('phase') == 'Succeeded' and worker.get('exported') is True and
                worker.get('gpu_executed') is False and worker.get('completed_jobs') == 140 and
                worker.get('finite_work_completed_jobs') == 140 and worker.get('selected_cases_per_job') == 4 and
                worker.get('selected_cases') == 560, 'Incomplete or mismatched CPU worker qualification')
        archive = path.parent / ('worker-' + str(index) + '.tar.gz')
        require(sha(archive) == worker['archive_sha256'] and archive.stat().st_size == worker['archive_bytes'],
                'Original CPU archive changed')
        receipt, inventory = qualifier.review_archive(archive, expected, cpu_bytes, fixed)
        require(receipt['environment'].get('scope') == 'CPU_NATIVE_REFERENCE_ONLY' and
                receipt['gpu_executed'] is False, 'CPU model fixtures cannot qualify the native image')
        inventory_path = path.parent / ('artifact-inventory-' + str(index) + '.json')
        require(sha(inventory_path) == worker['artifact_inventory_sha256'] and load(inventory_path) == inventory,
                'CPU original artifact inventory changed')
        for label in ('stdout', 'stderr'):
            require(sha(path.parent / ('pod-' + str(index) + '.' + label)) == worker[label + '_sha256'],
                    'CPU original pod log changed')
        verified.append({'node': worker['node'], 'archive': archive, 'receipt': receipt, 'inventory': inventory})
    cleanup = load(path.parent / 'cleanup.json')
    require(isinstance(cleanup.get('namespace_deleted'), str) and cleanup['namespace_deleted'] and
            cleanup.get('failure_type') is None, 'Completed CPU namespace cleanup required')
    return kind, verified


def verify_independent_review(path, kind, workers, spec, spec_sha256):
    review = load(path)
    require(review.get('state') == REVIEW_STATE and review.get('gpu_executed') is False and
            review.get('harness_sha256') == spec['harness_sha256'] and
            review.get('shared_harness_sha256') == spec['shared_harness_sha256'] and
            review.get('protocol_sha256') == spec['protocol_sha256'] and
            review.get('reserved_schedule_sha256') == spec['reserved_schedule_sha256'] and
            review.get('gpu_spec_sha256') == spec_sha256 and review.get('audited_jobs') == 280 and
            review.get('audited_selected_cases') == 1120 and
            review.get('all_original_payload_bytes_unchanged') is True and
            review.get('reviewer_sha256') == sha(ROOT / 'scripts/analyze-fixed-work-campaign.py') and
            len(review.get('workers', [])) == 2, 'Independent semantic review of all 1120 CPU originals required')
    for observed, worker in zip(review['workers'], workers):
        original_receipt, archive = worker['receipt'], worker['archive']
        require(observed['worker'] == worker['node'] and Path(observed['archive_file']).resolve() == archive.resolve() and
                observed['archive_sha256'] == sha(archive) and observed['archive_bytes'] == archive.stat().st_size and
                observed['audited_jobs'] == 140 and observed['audited_selected_cases'] == 560 and
                observed['selected_case_target'] == 4 and observed['backend'] == 'native-reference' and
                observed['scope'] == 'CPU_NATIVE_REFERENCE_ONLY', 'Independent audit does not match original CPU worker')
        individual_path = Path(observed['audit_file'])
        require(sha(individual_path) == observed['audit_sha256'], 'Individual independent CPU review changed')
        individual = load(individual_path)
        require(individual.get('state') == 'PASS_CPU_FIXED_WORK_DIAGNOSTIC_AUDIT' and
                individual.get('gpu_executed') is False and individual.get('full_gpu_quota_matrix') is False and
                individual.get('audited_jobs') == 140 and individual.get('audited_selected_cases') == 560 and
                individual.get('spec_sha256') == kind['spec_sha256'] and
                individual.get('receipt_sha256') == worker['inventory']['evidence/runs/receipt.json']['sha256'] and
                individual.get('harness_sha256') == spec['harness_sha256'] and
                individual.get('shared_harness_sha256') == spec['shared_harness_sha256'] and
                individual.get('protocol_sha256') == spec['protocol_sha256'] and
                individual.get('reserved_schedule_sha256') == spec['reserved_schedule_sha256'] and
                individual.get('all_case_traces_independently_recomputed') is True and
                individual.get('raw_files_modified') is False and individual.get('candidate_failures') == 0 and
                not individual.get('missing_jobs') and not individual.get('partial_jobs'),
                'Independent CPU audit scope, original receipt or source changed')
        rows = individual['job_rows']
        require(len(rows) == 140, 'Independent review must describe every original CPU job')
        for row, entry in zip(rows, original_receipt['jobs']):
            require(row['run_id'] == entry['run_id'] and row['raw_sha256'] == entry['raw_sha256'] and
                    row['block'] == entry['configuration']['block'] and row['method'] == entry['configuration']['method'] and
                    row['seed'] == entry['configuration']['seed'] and row['fixed_work_complete'] is True and
                    row['gpu_executed'] is False and row['scope'] == 'CPU_NATIVE_REFERENCE_ONLY' and
                    row['selected_cases'] == 4 and row['selected_case_target'] == 4,
                    'Independent CPU job review differs from actual original records')
    return review


def verify_local_qualification(path, spec, spec_sha256):
    local = load(path)
    require(local.get('state') == LOCAL_STATE and local.get('scope') == LOCAL_SCOPE and
            local.get('gpu_executed') is False and local.get('spec_sha256') == spec_sha256 and
            local.get('harness_sha256') == spec['harness_sha256'] and
            local.get('helper_harness_sha256') == spec['shared_harness_sha256'] and
            local.get('protocol_sha256') == spec['protocol_sha256'] and
            local.get('reserved_schedule_sha256') == spec['reserved_schedule_sha256'] and
            isinstance(local.get('checks'), dict) and
            all(local['checks'].get(name) == 'PASS' for name in CHECKS),
            'Matching completed local CPU and mocked-cloud qualification required')
    for field, filename in (('cloud_controller_sha256', 'azure-window.py'),
                            ('host_script_sha256', 'qualify-host.sh'),
                            ('resume_controller_sha256', 'azure-resume-campaign.py')):
        require(local.get(field) == sha(ROOT / 'scripts' / filename), 'Qualified infrastructure source changed: ' + filename)
    logs = local.get('log_files', [])
    require(isinstance(logs, list) and logs, 'Original local qualification log hashes required')
    seen = set()
    for row in logs:
        log = Path(row['path'])
        require(log.is_absolute() and str(log.resolve()) not in seen and log.is_file() and not log.is_symlink() and
                sha(log) == row['sha256'] and log.stat().st_size == row['bytes'], 'Original local qualification log changed')
        seen.add(str(log.resolve()))
    return local


def verify_local_gates(bundle):
    """Revalidate every original local gate before any cloud plan/apply/resume."""
    require(bundle.get('schema_version') == 3 and bundle.get('transport') == 'FIXED_WORK_IR_CAMPAIGN' and
            bundle.get('campaign_id') == CAMPAIGN_ID and bundle.get('planned_jobs') == 140 and
            bundle.get('selected_cases_per_job') == 100 and bundle.get('gpu_jobs_parallel') is False and
            bundle.get('archive_download_byte_limit') == 8589934592 and
            bundle.get('model_download_required') is False, 'Fixed-work campaign bundle scope or guards changed')
    fixed = module('run-fixed-work-campaign.py', 'fixed_bundle_exact_spec')
    spec_path = bound_path(bundle, 'campaign_spec')
    spec = load(spec_path)
    require(spec == fixed.make_spec('cuda'), 'GPU campaign specification differs from the immutable protocol')
    require(bundle.get('campaign_harness_sha256') == spec['harness_sha256'] and
            bundle.get('helper_harness_sha256') == spec['shared_harness_sha256'], 'Campaign/helper code hash binding changed')
    protocol, reserved = bound_path(bundle, 'protocol'), bound_path(bundle, 'reserved_schedule')
    require(sha(protocol) == fixed.PROTOCOL_SHA256 and sha(reserved) == fixed.RESERVED_SCHEDULE_SHA256,
            'Frozen protocol or original reserved schedule changed')
    images, gates = qualified_images()
    require(bundle.get('images') == images and bundle.get('image_gates') == gates,
            'Campaign must use only the original qualified CUDA and IR image digests')
    kind_path = bound_path(bundle, 'cpu_kind_receipt')
    kind, workers = verify_kind(kind_path, spec, fixed)
    require(kind['image_id'] == gates['ir']['image_id'], 'CPU campaign image differs from the qualified IR image')
    review = verify_independent_review(bound_path(bundle, 'independent_cpu_review'), kind, workers,
                                       spec, bundle['campaign_spec_sha256'])
    local = verify_local_qualification(bound_path(bundle, 'local_qualification'), spec, bundle['campaign_spec_sha256'])
    return {'verified': True, 'gpu_executed': False, 'scope': LOCAL_SCOPE,
            'cpu_jobs': 280, 'cpu_selected_cases': 1120,
            'independent_review_state': review['state'], 'local_qualification_state': local['state']}


def make_bundle(spec_path, protocol_path, reserved_schedule_path, kind_receipt_path,
                independent_cpu_review_path, local_qualification_path):
    fixed = module('run-fixed-work-campaign.py', 'fixed_bundle_declaration')
    images, gates = qualified_images()
    bundle = {'schema_version': 3, 'transport': 'FIXED_WORK_IR_CAMPAIGN', 'campaign_id': CAMPAIGN_ID,
              'images': images, 'image_gates': gates,
              'campaign_harness_sha256': fixed.harness_sha256(),
              'helper_harness_sha256': fixed.SHARED_HARNESS_SHA256,
              'planned_jobs': 140, 'selected_cases_per_job': 100,
              'gpu_jobs_parallel': False, 'archive_download_byte_limit': 8589934592,
              'model_download_required': False, 'local_functional_selected_case_target': 4}
    for prefix, path in (('campaign_spec', spec_path), ('protocol', protocol_path),
                         ('reserved_schedule', reserved_schedule_path), ('cpu_kind_receipt', kind_receipt_path),
                         ('independent_cpu_review', independent_cpu_review_path),
                         ('local_qualification', local_qualification_path)):
        bundle[prefix + '_path'], bundle[prefix + '_sha256'] = str(Path(path).resolve()), sha(path)
    verify_local_gates(bundle)
    return bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True, type=Path)
    parser.add_argument('--protocol', required=True, type=Path)
    parser.add_argument('--reserved-schedule', required=True, type=Path)
    parser.add_argument('--kind-receipt', required=True, type=Path)
    parser.add_argument('--independent-cpu-review', required=True, type=Path)
    parser.add_argument('--local-qualification', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    bundle = make_bundle(args.spec, args.protocol, args.reserved_schedule, args.kind_receipt,
                         args.independent_cpu_review, args.local_qualification)
    with args.output.open('x') as output:
        json.dump(bundle, output, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    args.output.chmod(0o444)
    print(json.dumps({'bundle_file': str(args.output), 'bundle_sha256': sha(args.output),
                      'planned_jobs': 140, 'gpu_created': False}))


if __name__ == '__main__':
    main()
