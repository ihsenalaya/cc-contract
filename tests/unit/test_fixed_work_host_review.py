"""CPU fixtures for bounded extraction, release prerequisites and RS256 claims."""
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def import_script(name, filename):
    loader = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    result = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(result)
    return result


reviewer = import_script('fixed_work_host_test', 'review-fixed-work-host.py')
host = import_script('fixed_work_host_crypto_test', 'review-gpu-window.py')
fixed = import_script('fixed_work_host_spec_test', 'run-fixed-work-campaign.py')


def archive_file(path, files):
    sums = ''.join(hashlib.sha256(data).hexdigest() + '  ./' + name + '\n' for name, data in files.items())
    with tarfile.open(path, 'w:gz') as archive:
        for name, data in {**files, 'SHA256SUMS': sums.encode()}.items():
            member = tarfile.TarInfo('cc-contract-evidence/' + name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


class FixedWorkHostReviewTests(unittest.TestCase):
    def test_release_is_required_before_archive_hash_or_output_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, output = Path(temporary), Path(temporary) / 'review'
            (directory / 'collection.json').write_text(json.dumps({'archive_file': 'original.tar.gz',
                'timestamp_utc': '2026-10-09T21:00:00+00:00'}))
            (directory / 'release.json').write_text(json.dumps({'power_state': 'PowerState/running',
                'timestamp_utc': '2026-10-09T21:01:00+00:00'}))
            with patch.object(reviewer, 'sha') as digest:
                with self.assertRaisesRegex(ValueError, 'Confirmed deallocation'):
                    reviewer.review(directory, output)
                digest.assert_not_called()
            self.assertFalse(output.exists())

    def test_named_streaming_extraction_preserves_bytes_ignores_campaign_trace(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive, output = directory / 'original.tar.gz', directory / 'named'
            output.mkdir()
            files = {'commands.tsv': b'ORIGINAL COMMAND BYTES\n',
                     'ir-reference.stdout': b'ORIGINAL QUALIFICATION BYTES\n',
                     'fixed-work-campaign/runs/campaign-fixture/records.jsonl': b'CPU FIXTURE TRACE\n' * 200000}
            archive_file(archive, files)
            before = reviewer.sha(archive)
            captured = reviewer.extract_named_inputs(archive, output)
            self.assertEqual(set(captured), {'commands.tsv', 'ir-reference.stdout', 'SHA256SUMS'})
            for name in ('commands.tsv', 'ir-reference.stdout'):
                self.assertEqual((output / name).read_bytes(), files[name])
                self.assertEqual(captured[name]['sha256'], hashlib.sha256(files[name]).hexdigest())
            self.assertEqual({p.name for p in output.iterdir()}, set(captured))
            self.assertEqual(reviewer.sha(archive), before)

    def test_total_extraction_limit_and_links_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive, output = directory / 'original.tar.gz', directory / 'bounded'
            output.mkdir()
            archive_file(archive, {'commands.tsv': b'123456789', 'ir-reference.stdout': b'123456789'})
            with patch.object(reviewer, 'MAX_EXTRACTED_BYTES', 16):
                with self.assertRaisesRegex(ValueError, '128 MiB total'):
                    reviewer.extract_named_inputs(archive, output)
            linked = directory / 'linked.tar.gz'
            with tarfile.open(linked, 'w:gz') as archive:
                member = tarfile.TarInfo('cc-contract-evidence/cpu-attestation.stdout')
                member.type = tarfile.SYMTYPE
                member.linkname = '/outside'
                archive.addfile(member)
            with self.assertRaisesRegex(ValueError, 'invalid named review input'):
                reviewer.extract_named_inputs(linked, output)

    def test_real_rs256_signature_selected_claims_and_vm_binding(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = key.public_key().public_numbers()
        def encode(data):
            return base64.urlsafe_b64encode(data).decode().rstrip('=')
        now = int(datetime.now(timezone.utc).timestamp())
        uuid = '11111111-2222-3333-4444-555555555555'
        header = encode(json.dumps({'alg': 'RS256', 'kid': 'CPU_FIXTURE_KEY'}).encode())
        payload = encode(json.dumps({'iss': host.ISSUER, 'nbf': now - 5, 'iat': now, 'exp': now + 120,
            'x-ms-azurevm-vmid': uuid, 'secureboot': True, 'x-ms-azurevm-kerneldebug-enabled': False,
            'x-ms-azurevm-hypervisordebug-enabled': False, 'x-ms-isolation-tee': {
                'x-ms-attestation-type': 'sevsnpvm', 'x-ms-compliance-status': 'azure-compliant-cvm',
                'x-ms-sevsnpvm-is-debuggable': False}}).encode())
        signature = encode(key.sign((header + '.' + payload).encode(), padding.PKCS1v15(), hashes.SHA256()))
        jwks = {'keys': [{'kid': 'CPU_FIXTURE_KEY', 'kty': 'RSA',
            'n': encode(public.n.to_bytes((public.n.bit_length() + 7) // 8, 'big')),
            'e': encode(public.e.to_bytes((public.e.bit_length() + 7) // 8, 'big'))}]}
        token = header + '.' + payload + '.' + signature
        result = host.verify_cpu(token, jwks, uuid, now)
        self.assertTrue(result['signature_verified'])
        self.assertFalse(result['provider_TEE_signing_key_binding_independently_checked'])
        with self.assertRaises(AssertionError):
            host.verify_cpu(token, jwks, 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', now)
        with self.assertRaises(AssertionError):
            host.verify_cpu(token, jwks, uuid, now + 200)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cache = directory / 'cached.json'
            cache.write_text(json.dumps(jwks))
            output = directory / 'review'; output.mkdir()
            with patch.object(reviewer.urllib.request, 'urlopen') as fetch:
                with self.assertRaisesRegex(ValueError, 'matching JWKS cache hash'):
                    reviewer.signing_keys(output, host, cache, '0' * 64)
                fetch.assert_not_called()
                loaded, digest = reviewer.signing_keys(output, host, cache, reviewer.sha(cache))
                self.assertEqual(loaded, jwks)
                self.assertEqual(digest, reviewer.sha(cache))

    def test_partial_host_roundtrip_keeps_originals_and_never_claims_e0_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'fixed-work-1010a'; directory.mkdir()
            output = Path(temporary) / 'review'
            spec_bytes = (ROOT / 'experiments/fixed-work-campaign-spec.json').read_bytes()
            files = {'commands.tsv': b'2026-10-09T21:00:00Z\tkernel\t1\n',
                'sample-inputs/spec.json': spec_bytes,
                'sample-inputs/run-fixed-work-campaign.py': (ROOT / 'scripts/run-fixed-work-campaign.py').read_bytes(),
                'sample-inputs/run-work-sample.py': (ROOT / 'scripts/run-work-sample.py').read_bytes(),
                'sample-inputs/fixed-work-campaign-v0.3.md': (ROOT / fixed.PROTOCOL_FILE).read_bytes(),
                'sample-inputs/comparison-schedule.json': (ROOT / fixed.RESERVED_SCHEDULE_FILE).read_bytes(),
                'fixed-work-campaign/runs/campaign-fixture/records.jsonl': b'CPU FIXTURE ONLY\n'}
            archive = directory / 'original.tar.gz'; archive_file(archive, files)
            collection = {'archive_file': archive.name, 'archive_sha256': reviewer.sha(archive),
                'timestamp_utc': '2026-10-09T21:00:00+00:00', 'files_verified': len(files),
                'remote_evidence_directory': '/home/cccontract/cc-campaigns/fixed-work-1010a/cc-contract-evidence'}
            (directory / 'collection.json').write_text(json.dumps(collection))
            (directory / 'release.json').write_text(json.dumps({'power_state': 'PowerState/deallocated',
                'timestamp_utc': '2026-10-09T21:01:00+00:00'}))
            bundle = {'transport': 'FIXED_WORK_IR_CAMPAIGN', 'campaign_id': directory.name}
            for original, field in [('sample-inputs/spec.json', 'campaign_spec_sha256'),
                ('sample-inputs/run-fixed-work-campaign.py', 'campaign_harness_sha256'),
                ('sample-inputs/run-work-sample.py', 'helper_harness_sha256'),
                ('sample-inputs/fixed-work-campaign-v0.3.md', 'protocol_sha256'),
                ('sample-inputs/comparison-schedule.json', 'reserved_schedule_sha256')]:
                bundle[field] = hashlib.sha256(files[original]).hexdigest()
            (directory / 'workload-bundle.json').write_text(json.dumps(bundle))
            with patch.object(reviewer.urllib.request, 'urlopen') as fetch:
                result = reviewer.review(directory, output)
                fetch.assert_not_called()
            self.assertEqual(result['state'], 'PARTIAL_HOST_OR_IR_QUALIFICATION_REVIEW')
            self.assertFalse(result['full_E0_complete'])
            self.assertFalse(result['GPU_quote_or_local_HMAC_independently_authenticated'])
            self.assertFalse(result['campaign_raw_files_extracted'])
            self.assertTrue(result['original_archive_bytes_unchanged'])
            self.assertTrue((output / 'independent-fixed-work-host-review.json').is_file())
            self.assertEqual(reviewer.sha(archive), collection['archive_sha256'])


if __name__ == '__main__':
    unittest.main()
