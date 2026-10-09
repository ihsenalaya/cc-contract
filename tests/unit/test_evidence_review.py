"""CPU fixtures test review rejection paths; none constitutes attestation evidence."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('review', ROOT / 'scripts/review-gpu-window.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def encoded(value):
    raw = json.dumps(value).encode() if isinstance(value, dict) else value
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


class AttestationReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        numbers = cls.key.public_key().public_numbers()
        cls.jwks = {'keys': [{'kty': 'RSA', 'kid': 'MOCK_FIXTURE_ONLY', 'e': encoded(numbers.e.to_bytes(3, 'big')), 'n': encoded(numbers.n.to_bytes(256, 'big'))}]}

    def fixture(self):
        claims = {'iss': review.ISSUER, 'nbf': 100, 'iat': 100, 'exp': 200,
                  'x-ms-azurevm-vmid': 'MOCK_VM_ONLY', 'secureboot': True,
                  'x-ms-azurevm-kerneldebug-enabled': False, 'x-ms-azurevm-hypervisordebug-enabled': False,
                  'x-ms-isolation-tee': {'x-ms-attestation-type': 'sevsnpvm', 'x-ms-compliance-status': 'azure-compliant-cvm', 'x-ms-sevsnpvm-is-debuggable': False}}
        header = encoded({'alg': 'RS256', 'kid': 'MOCK_FIXTURE_ONLY'})
        body = encoded(claims)
        signature = self.key.sign((header + '.' + body).encode(), padding.PKCS1v15(), hashes.SHA256())
        return header + '.' + body + '.' + encoded(signature)

    def test_tampered_payload_is_rejected_cryptographically(self):
        token = self.fixture()
        review.verify_cpu(token, self.jwks, 'MOCK_VM_ONLY', 105)
        h, b, sig = token.split('.')
        claims = json.loads(review.decode(b))
        claims['secureboot'] = False
        with self.assertRaises(InvalidSignature):
            review.verify_cpu(h + '.' + encoded(claims) + '.' + sig, self.jwks, 'MOCK_VM_ONLY', 105)

    def test_wrong_vm_identity_is_rejected(self):
        with self.assertRaises(AssertionError):
            review.verify_cpu(self.fixture(), self.jwks, 'OTHER_MOCK_VM', 105)

    def test_expired_attestation_is_rejected_at_observation_time(self):
        with self.assertRaises(AssertionError):
            review.verify_cpu(self.fixture(), self.jwks, 'MOCK_VM_ONLY', 205)


class CudaReviewTests(unittest.TestCase):
    def fixture(self):
        # Synthetic CPU records exercise the reviewer; provenance is deliberately fake.
        rows = [{'record_type': 'environment', 'device_count': 1}]
        for repeat in range(3):
            layouts = [(f, 128, repeat * 10 + g, False) for f in ['T01', 'T02', 'T03', 'T05'] for g in range(3 if f in ['T02', 'T05'] else 1)]
            layouts += [('T06', n, repeat, False) for n in [1, 2, 31, 32, 33, 255, 256, 257, 4096]]
            layouts += [('E0_KERNEL_REFERENCE', 4096, repeat, True)]
            for family, size, generation, kernel in layouts:
                data = [generation] + [((i * 17 + generation * 31) % 8191 - 4095) for i in range(1, size)]
                if kernel:
                    data = [data[0]] + [2 * x + 1 for x in data[1:]]
                rows.append({'record_type': 'case', 'family': family, 'repeat': repeat, 'size': size, 'generation': generation, 'kernel': kernel, 'expected': data, 'observed': list(data), 'gpu_executed': True, 'seed': 0, 'scope': 'REAL_CUDA_CC_NOT_YET_QUALIFIED', 'verdict': 'PASS', 'oracle_verdict': 'PASS', 'duration_seconds': 0.1, 'synchronization': 'event_wait_then_stream_sync' if family == 'T03' else 'same_stream_then_stream_sync', 'run_id': 'MOCK_CPU_FIXTURE_ONLY', 'git_commit': '0' * 40, 'image_digest': 'ghcr.io/ihsenalaya/cc-contract-cuda@sha256:' + '0' * 64})
        return rows

    def test_self_consistent_wrong_arrays_are_rejected(self):
        rows = self.fixture()
        self.assertEqual(review.review_cuda(rows)['observations'], 54)
        mutated = copy.deepcopy(rows)
        mutated[1]['expected'][1] += 1
        mutated[1]['observed'][1] += 1
        with self.assertRaises(AssertionError):
            review.review_cuda(mutated)

    def test_missing_observation_is_rejected(self):
        with self.assertRaises(AssertionError):
            review.review_cuda(self.fixture()[:-1])


if __name__ == '__main__':
    unittest.main()
