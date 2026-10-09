"""Review bounded host/MAA/CUDA/IR originals after confirmed deallocation.

The large campaign TAR is inventoried in streaming mode, then scanned once for
explicitly named host inputs. Campaign traces are never extracted or reviewed
here. GPU quotes, local HMAC receipts and NRAS remain independently unverified.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
MAX_EXTRACTED_BYTES = 128 * 1024 * 1024
MAX_JWKS_BYTES = 1024 * 1024
NAMES = {name: name for name in (
    'SHA256SUMS', 'commands.tsv', 'timings.tsv', 'kernel-version.stdout',
    'driver-version.stdout', 'cc-mode.stdout', 'cc-environment.stdout',
    'secure-boot.stdout', 'cpu-attestation.stdout', 'gpu-attestation.stdout',
    'cuda-reference.stdout', 'ir-reference.stdout')}
NAMES.update({'sample-inputs/' + name: name for name in (
    'run-fixed-work-campaign.py', 'run-work-sample.py', 'fixed-work-campaign-v0.3.md',
    'comparison-schedule.json')})
NAMES['sample-inputs/spec.json'] = 'campaign-spec.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def module(filename, name):
    loader = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    loaded = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(loaded)
    return loaded


def utc():
    return datetime.now(timezone.utc).isoformat()


def stamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0, 'UTC timestamp required')
    return parsed.timestamp()


def write(path, value):
    with path.open('x') as target:
        json.dump(value, target, indent=2)
        target.write('\n')
        target.flush()
        os.fsync(target.fileno())
    path.chmod(0o444)


def release_gate(directory):
    collection = json.loads((directory / 'collection.json').read_bytes())
    release = json.loads((directory / 'release.json').read_bytes())
    require(release['power_state'] == 'PowerState/deallocated' and
            stamp(release['timestamp_utc']) >= stamp(collection['timestamp_utc']),
            'Confirmed deallocation after collection required before host review')
    filename = collection['archive_file']
    require(isinstance(filename, str) and Path(filename).name == filename and '\\' not in filename,
            'Unsafe original archive filename')
    archive = directory / filename
    require(archive.is_file() and not archive.is_symlink(), 'Missing or unsafe original archive')
    return collection, release, archive


def extract_named_inputs(archive_path, output):
    """Copy only constant mapped names; preserve exact original bytes, bounded."""
    captured, total = {}, 0
    with tarfile.open(archive_path, 'r|gz') as archive:
        for member in archive:
            prefix = 'cc-contract-evidence/'
            relative = member.name[len(prefix):] if member.name.startswith(prefix) else None
            if relative not in NAMES:
                continue
            require(relative not in captured and member.isfile() and member.size >= 0,
                    'Duplicate or invalid named review input')
            require(member.size <= MAX_EXTRACTED_BYTES - total, 'Named host review inputs exceed 128 MiB total')
            if relative == 'SHA256SUMS':
                require(member.size <= 2 * 1024 * 1024, 'Oversized original hash manifest')
            destination = output / NAMES[relative]
            digest, size = hashlib.sha256(), 0
            with archive.extractfile(member) as source, destination.open('xb') as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk); size += len(chunk); target.write(chunk)
                target.flush(); os.fsync(target.fileno())
            require(size == member.size, 'Truncated original named review input')
            destination.chmod(0o444)
            total += size
            captured[relative] = {'local_file': destination.name, 'bytes': size, 'sha256': digest.hexdigest()}
    require('SHA256SUMS' in captured, 'Original SHA256SUMS missing')
    sums = {}
    for line in (output / 'SHA256SUMS').read_text().splitlines():
        require(re.fullmatch(r'[a-f0-9]{64}  \./[^\n]+', line) is not None, 'Malformed original hash record')
        digest, name = line.split('  ', 1)
        require(name[2:] not in sums, 'Duplicate original hash record')
        sums[name[2:]] = digest
    for relative, observed in captured.items():
        if relative != 'SHA256SUMS':
            require(sums.get(relative) == observed['sha256'], 'Named review input differs from original hash manifest')
    return captured


def signing_keys(output, host, cache=None, cache_sha256=None):
    destination = output / 'cpu-signing-jwks.json'
    if cache is not None:
        require(cache_sha256 is not None and sha(cache) == cache_sha256, 'Explicit matching JWKS cache hash required')
        require(cache.stat().st_size <= MAX_JWKS_BYTES, 'JWKS cache exceeds bounded size')
        data = cache.read_bytes()
    else:
        require(cache_sha256 is None, 'JWKS hash requires an explicit cache file')
        with urllib.request.urlopen(host.ISSUER + '/certs', timeout=30) as response:
            require(response.url.startswith(host.ISSUER + '/'), 'MAA signing-key HTTPS issuer changed')
            data = response.read(MAX_JWKS_BYTES + 1)
        require(len(data) <= MAX_JWKS_BYTES, 'MAA signing-key response exceeds bounded size')
    jwks = json.loads(data)
    require(isinstance(jwks, dict) and isinstance(jwks.get('keys'), list), 'Malformed MAA signing keys')
    with destination.open('xb') as target:
        target.write(data); target.flush(); os.fsync(target.fileno())
    destination.chmod(0o444)
    return jwks, sha(destination)


def review(directory, output, jwks_cache=None, jwks_sha256=None):
    directory, output = Path(directory), Path(output)
    collection, release, archive_path = release_gate(directory)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    started_ns, started_utc = time.monotonic_ns(), utc()
    result = {'schema_version': 3, 'state': 'NOT_FINISHED',
              'scope': 'PARTIAL_E0_REAL_HOST_CUDA_AND_IR_INDEPENDENT_CPU_REVIEW',
              'started_utc': started_utc, 'started_monotonic_ns': started_ns,
              'release_confirmed_before_review': True, 'GPU_or_VM_mutations_performed': False,
              'collection_receipt_sha256': sha(directory / 'collection.json'),
              'release_receipt_sha256': sha(directory / 'release.json'),
              'review_helper_sha256': sha(Path(__file__)), 'phases': [],
              'full_E0_complete': False, 'CPU_MAA_signing_key_binding_to_TEE_independently_verified': False,
              'GPU_quote_or_local_HMAC_independently_authenticated': False, 'NRAS_token_verified': False,
              'campaign_raw_files_extracted': False}
    try:
        beginning = time.monotonic_ns()
        require(sha(archive_path) == collection['archive_sha256'], 'Original collection archive hash differs')
        result.update(original_archive_sha256=collection['archive_sha256'], original_archive_bytes=archive_path.stat().st_size)
        cloud = module('azure-window.py', 'fixed_host_streaming_inventory')
        require(cloud.verify_evidence_archive(archive_path) == collection['files_verified'], 'Original inventory count differs')
        result['all_original_file_hashes_verified'] = True
        captured = extract_named_inputs(archive_path, output)
        result['original_named_review_input_hashes'] = captured
        result['phases'].append({'phase': 'streaming_inventory_and_one_named_extraction_pass',
                                 'elapsed_seconds': (time.monotonic_ns() - beginning) / 1e9})
        bundle = json.loads((directory / 'workload-bundle.json').read_bytes())
        require(bundle.get('transport') == 'FIXED_WORK_IR_CAMPAIGN' and bundle.get('campaign_id') == directory.name,
                'Actual campaign identity or workload transport differs')
        expected_root = '/home/cccontract/cc-campaigns/' + directory.name + '/cc-contract-evidence'
        require(collection.get('remote_evidence_directory') == expected_root, 'Collection contains another remote evidence directory')
        fixed = module('run-fixed-work-campaign.py', 'fixed_host_spec_binding')
        spec = json.loads((output / 'campaign-spec.json').read_bytes())
        require(spec == fixed.make_spec('cuda'), 'Executed campaign spec differs from the frozen protocol')
        for original, field in (('sample-inputs/spec.json', 'campaign_spec_sha256'),
                                ('sample-inputs/run-fixed-work-campaign.py', 'campaign_harness_sha256'),
                                ('sample-inputs/run-work-sample.py', 'helper_harness_sha256'),
                                ('sample-inputs/fixed-work-campaign-v0.3.md', 'protocol_sha256'),
                                ('sample-inputs/comparison-schedule.json', 'reserved_schedule_sha256')):
            require(captured.get(original, {}).get('sha256') == bundle[field], 'Transferred original campaign source binding differs')
        commands = {}
        for line in (output / 'commands.tsv').read_text().splitlines():
            timestamp, label, code = line.split('\t')
            require(label not in commands, 'Duplicate host command identity')
            commands[label] = {'timestamp_utc': timestamp, 'exit_code': int(code) if code.isdecimal() else code}
        required = ('kernel', 'kernel-version', 'nvidia-info', 'driver-version', 'cc-mode',
                    'cc-environment', 'secure-boot', 'cpu-attestation', 'gpu-attestation', 'cuda-reference')
        host_ready = all(commands.get(name, {}).get('exit_code') == 0 for name in required)
        if host_ready:
            beginning = time.monotonic_ns()
            require((output / 'kernel-version.stdout').read_text().strip() == '6.8.0-1066-azure-fde', 'Host kernel pin differs')
            require((output / 'driver-version.stdout').read_text().strip() == '595.91.07', 'Host driver pin differs')
            require(re.search(r'CC status:\s*ON\s*$', (output / 'cc-mode.stdout').read_text()) is not None,
                    'Confidential computing must be ON')
            require('PRODUCTION' in (output / 'cc-environment.stdout').read_text() and
                    'SecureBoot enabled' in (output / 'secure-boot.stdout').read_text(), 'CC production or SecureBoot gate differs')
            host = module('review-gpu-window.py', 'fixed_host_attestation_and_cuda_functions')
            result['host_reviewer_source_sha256'] = sha(ROOT / 'scripts/review-gpu-window.py')
            jwks, keys_sha = signing_keys(output, host, jwks_cache, jwks_sha256)
            identity = json.loads((directory / 'vm-identity.json').read_bytes())
            vm_uuid = identity[0]['instances'][0]['attributes']['virtual_machine_id']
            require(re.fullmatch(r'[a-f0-9-]{36}', vm_uuid.lower()) is not None, 'Actual VM UUID missing')
            plan = json.loads((directory / 'approved-workload-plan.json').read_bytes())
            require(plan['retained_vm_uuid'].lower() == vm_uuid.lower(), 'Retained VM UUID differs from the executed plan')
            cpu_tokens = host.tokens((output / 'cpu-attestation.stdout').read_text())
            require(len(cpu_tokens) == 1, 'Exactly one original CPU MAA token required')
            cpu = host.verify_cpu(cpu_tokens[0], jwks, vm_uuid, stamp(commands['cpu-attestation']['timestamp_utc']))
            gpu_tokens = host.tokens((output / 'gpu-attestation.stdout').read_text())
            require(len(gpu_tokens) == 2, 'Two original local GPU verifier receipts required')
            gpu = [json.loads(host.decode(token.split('.')[1])) for token in gpu_tokens]
            require(all(json.loads(host.decode(token.split('.')[0]))['alg'] == 'HS256' for token in gpu_tokens) and
                    all(claims['iss'] == 'LOCAL_GPU_VERIFIER' for claims in gpu), 'Unexpected local GPU receipt issuer/algorithm')
            outer = next(claims for claims in gpu if 'x-nvidia-overall-att-result' in claims)
            inner = next(claims for claims in gpu if 'measres' in claims)
            checks = {key: value for key, value in inner.items() if key.startswith('x-nvidia-gpu-') and type(value) is bool}
            require(outer['x-nvidia-overall-att-result'] is True and inner['measres'] == 'success' and
                    outer['eat_nonce'] == inner['eat_nonce'] and inner['dbgstat'] == 'disabled' and
                    inner['secboot'] is True and len(checks) == 16 and all(checks.values()), 'Local reported GPU verifier checks incomplete')
            rows = [json.loads(line) for line in (output / 'cuda-reference.stdout').read_text().splitlines()]
            cuda = host.review_cuda(rows)
            require(cuda['image_digest'] == bundle['images']['cuda'] and
                    cuda['git_commit'] == bundle['image_gates']['cuda']['source_commit'], 'CUDA qualification image/source differs')
            result['host_review'] = {'state': 'PASS_BOUNDED_HOST_MAA_RS256_AND_CUDA_54_OBSERVATIONS',
                'cpu_attestation': cpu, 'cpu_jwks_sha256': keys_sha, 'cuda': cuda,
                'kernel_and_driver_exact_pins_verified': True, 'CC_ON_PRODUCTION_and_SecureBoot_verified': True,
                'GPU_HMAC_receipts_independently_authenticated': False,
                'GPU_hardware_quote_independently_verified': False, 'NRAS_token_verified': False,
                'local_reported_checks_all_true': True}
            result['phases'].append({'phase': 'MAA_RS256_VM_identity_host_and_CUDA54',
                                     'elapsed_seconds': (time.monotonic_ns() - beginning) / 1e9})
        else:
            result['host_review'] = {'state': 'NOT_RUN_INCOMPLETE_HOST_GATES',
                                    'missing_or_failed_gates': [name for name in required if commands.get(name, {}).get('exit_code') != 0]}
        ir_ready = commands.get('ir-reference', {}).get('exit_code') == 0 and 'ir-reference.stdout' in captured
        if ir_ready:
            beginning = time.monotonic_ns()
            ir = module('review-ir-qualification.py', 'fixed_host_ir_original_review')
            original_ir = output / 'ir-reference.stdout'
            ir_result = ir.review(original_ir)
            require(ir_result['gpu_executed'] is True and ir_result['scope'] == 'REAL_CUDA_IR' and
                    ir_result['verdict'] == 'PASS' and ir_result['cases'] == 96 and
                    ir_result['observations'] == 252 and ir_result['counts'] == {'PASS': 96} and
                    ir_result['independently_recomputed'] is True, 'IR qualification incomplete or scope differs')
            summary = None
            with original_ir.open() as source:
                for line in source:
                    if line.strip() == '{':
                        summary = json.loads(line + source.read()); break
            require(summary is not None and summary['image_digest'] == bundle['images']['ir'] and
                    summary['git_commit'] == bundle['image_gates']['ir']['source_commit'] and
                    summary['working_tree_dirty'] is not True, 'IR image/source differs or image is dirty')
            result['IR_reviewer_source_sha256'] = sha(ROOT / 'scripts/review-ir-qualification.py')
            result['IR_review'] = ir_result
            result['phases'].append({'phase': 'IR96_252_observations_independent_deferred_model',
                                     'elapsed_seconds': (time.monotonic_ns() - beginning) / 1e9})
        else:
            result['IR_review'] = {'state': 'NOT_RUN_MISSING_OR_INCOMPLETE_IR_GATE'}
        result['state'] = ('PASS_BOUNDED_HOST_AND_IR_QUALIFICATION_REVIEW' if host_ready and ir_ready
                           else 'PARTIAL_HOST_OR_IR_QUALIFICATION_REVIEW')
    except BaseException as exc:
        result.update(state='FAILED_INDEPENDENT_REVIEW', error_type=type(exc).__name__, error_message=str(exc))
        raise
    finally:
        unchanged = sha(archive_path) == collection['archive_sha256']
        result['original_archive_bytes_unchanged'] = unchanged
        if not unchanged:
            result.update(state='FAILED_INDEPENDENT_REVIEW', error_type='ORIGINAL_ARCHIVE_CHANGED')
        result.update(finished_utc=utc(), finished_monotonic_ns=time.monotonic_ns())
        result['actual_review_seconds_including_hashes_extraction_and_cert_fetch'] = (result['finished_monotonic_ns'] - started_ns) / 1e9
        write(output / 'independent-fixed-work-host-review.json', result)
    require(result['original_archive_bytes_unchanged'], 'Original archive changed during review')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='Fresh private output directory')
    parser.add_argument('--jwks-cache', type=Path)
    parser.add_argument('--jwks-sha256')
    args = parser.parse_args(argv)
    result = review(args.directory, args.output, args.jwks_cache, args.jwks_sha256)
    print(json.dumps({'state': result['state'], 'review_seconds': result['actual_review_seconds_including_hashes_extraction_and_cert_fetch'],
                      'review_file': str(args.output / 'independent-fixed-work-host-review.json')}))
    return 0 if result['state'] == 'PASS_BOUNDED_HOST_AND_IR_QUALIFICATION_REVIEW' else 1


if __name__ == '__main__':
    sys.exit(main())
