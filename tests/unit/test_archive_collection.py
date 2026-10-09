"""CPU-only archive integrity tests; no Azure or GPU access."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location('archive_collection_window', ROOT / 'scripts/azure-window.py')
window = importlib.util.module_from_spec(loader)
loader.loader.exec_module(window)
PREFIX = 'cc-contract-evidence/'


class ArchiveCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def archive(self, entries, hashes=None, extra=None, manifest_first=False):
        expected = entries if hashes is None else hashes
        manifest = ''.join(hashlib.sha256(data).hexdigest() + '  ./' + name + '\n'
                           for name, data in expected).encode()
        members = [(PREFIX + name, data) for name, data in entries]
        manifest_entry = (PREFIX + 'SHA256SUMS', manifest)
        members = [manifest_entry] + members if manifest_first else members + [manifest_entry]
        path = self.directory / 'original.tar.gz'
        with tarfile.open(path, mode='w:gz') as archive:
            for name, data in members:
                member = tarfile.TarInfo(name);member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            if extra is not None:
                archive.addfile(extra)
        return path

    def test_tar_and_hash_orders_can_differ_and_manifest_can_come_first(self):
        entries = [('z/records.jsonl', b'CPU ORIGINAL Z\n'), ('a/start.json', b'CPU ORIGINAL A\n')]
        for manifest_first in (False, True):
            with self.subTest(manifest_first=manifest_first):
                archive = self.archive(entries, hashes=list(reversed(entries)), manifest_first=manifest_first)
                original = archive.read_bytes()
                actual_open = tarfile.open
                with patch('tarfile.open', wraps=actual_open) as opened:
                    self.assertEqual(window.verify_evidence_archive(archive), 2)
                self.assertEqual(opened.call_count, 1)
                self.assertEqual(opened.call_args.kwargs['mode'], 'r|gz')
                self.assertEqual(archive.read_bytes(), original)

    def test_corrupt_payload_is_rejected(self):
        archive = self.archive([('records.jsonl', b'CORRUPTED')], hashes=[('records.jsonl', b'ORIGINAL')])
        with self.assertRaisesRegex(ValueError, 'file hash mismatch'):
            window.verify_evidence_archive(archive)

    def test_duplicate_file_is_rejected_even_with_same_bytes(self):
        archive = self.archive([('records.jsonl', b'ORIGINAL'), ('records.jsonl', b'ORIGINAL')])
        with self.assertRaisesRegex(ValueError, 'Duplicate evidence archive entry'):
            window.verify_evidence_archive(archive)

    def test_path_traversal_and_absolute_or_foreign_paths_are_rejected(self):
        for name in ('../outside', '/absolute', 'cc-contract-evidence/../outside', 'foreign/file'):
            with self.subTest(name=name):
                extra = tarfile.TarInfo(name);extra.type = tarfile.DIRTYPE
                archive = self.archive([('records.jsonl', b'ORIGINAL')], extra=extra)
                with self.assertRaisesRegex(ValueError, 'Unsafe evidence archive path'):
                    window.verify_evidence_archive(archive)

    def test_unlisted_original_file_is_rejected(self):
        archive = self.archive([('a', b'A'), ('unlisted', b'UNLISTED')], hashes=[('a', b'A')])
        with self.assertRaisesRegex(ValueError, 'inventory is incomplete or contains unlisted'):
            window.verify_evidence_archive(archive)

    def test_missing_listed_file_is_rejected(self):
        archive = self.archive([('a', b'A')], hashes=[('a', b'A'), ('missing', b'MISSING')])
        with self.assertRaisesRegex(ValueError, 'inventory is incomplete or contains unlisted'):
            window.verify_evidence_archive(archive)

    def test_links_and_special_members_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            with self.subTest(kind=kind):
                extra = tarfile.TarInfo(PREFIX + 'unsafe');extra.type = kind
                extra.linkname = 'records.jsonl'
                archive = self.archive([('records.jsonl', b'ORIGINAL')], extra=extra)
                with self.assertRaisesRegex(ValueError, 'links and special entries are forbidden'):
                    window.verify_evidence_archive(archive)

    def test_missing_manifest_and_oversized_manifest_are_rejected(self):
        archive = self.directory / 'no-manifest.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            member = tarfile.TarInfo(PREFIX + 'records.jsonl');member.size = 1
            output.addfile(member, io.BytesIO(b'A'))
        with self.assertRaisesRegex(ValueError, 'Missing root evidence hash manifest'):
            window.verify_evidence_archive(archive)
        with tarfile.open(archive, 'w:gz') as output:
            data = b'x' * (2 * 1024 * 1024 + 1)
            member = tarfile.TarInfo(PREFIX + 'SHA256SUMS');member.size = len(data)
            output.addfile(member, io.BytesIO(data))
        with self.assertRaisesRegex(ValueError, 'hash manifest exceeds metadata bound'):
            window.verify_evidence_archive(archive)

    def test_success_and_corruption_both_release_compute_without_deletion(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt):
                source = self.archive([('records.jsonl', b'ORIGINAL')],
                                      hashes=[('records.jsonl', b'WRONG')] if corrupt else None)
                directory = self.directory / ('failure' if corrupt else 'success');directory.mkdir()
                def export(args, stdout, **kwargs):
                    with source.open('rb') as input_stream:
                        shutil.copyfileobj(input_stream, stdout)
                with patch.object(window, 'ensure_window', return_value=({}, {})), \
                     patch.object(window, 'ssh_args', return_value=['CPU_FIXTURE_EXPORT']), \
                     patch.object(window.subprocess, 'run', side_effect=export), \
                     patch.object(window, 'release') as release, patch.object(window, 'tf') as terraform:
                    if corrupt:
                        with self.assertRaisesRegex(ValueError, 'file hash mismatch'):
                            window.collect_and_release(directory)
                        self.assertFalse((directory / 'collection.json').exists())
                    else:
                        window.collect_and_release(directory)
                        receipt = json.loads((directory / 'collection.json').read_text())
                        self.assertEqual(receipt['files_verified'], 1)
                        self.assertEqual(receipt['archive_verification'], 'ONE_PASS_STREAMING_TAR_GZIP_COMPLETE_HASH_INVENTORY')
                    release.assert_called_once_with(directory)
                    terraform.assert_not_called()
                self.assertEqual(next(directory.glob('guest-evidence-*.tar.gz')).read_bytes(), source.read_bytes())


if __name__ == '__main__':
    unittest.main()
