"""Small CPU transport fixtures; no managed-identity or GPU qualification claims."""
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cc_contract.cloud_model import download,validate_spec


def fixture(data=b'CPU_BYTE_FIXTURE'):
    digest=hashlib.sha256(data).hexdigest()
    return {'account':'cccontract12345678','container':'models','files':[{'name':'config.json','blob':digest+'/config.json','sha256':digest,'bytes':len(data)}]}


class CloudModelTests(unittest.TestCase):
    def test_exact_bytes_are_verified_without_logging_credential(self):
        data=b'CPU_BYTE_FIXTURE';requests=[]
        def open_url(request,**kwargs):requests.append(request);return io.BytesIO(data)
        with tempfile.TemporaryDirectory() as tmp,patch('sys.stdout',new_callable=io.StringIO) as out:
            receipt=download(fixture(data),tmp,credential=lambda:'CPU_CREDENTIAL_FIXTURE',open_url=open_url)
            self.assertEqual((Path(tmp)/'config.json').read_bytes(),data)
            self.assertEqual(requests[0].get_header('Authorization'),'Bearer CPU_CREDENTIAL_FIXTURE')
            self.assertTrue(receipt['files'][0]['verified'])
            self.assertNotIn('CPU_CREDENTIAL_FIXTURE',out.getvalue())
            self.assertEqual((Path(tmp)/'config.json').stat().st_mode&0o777,0o444)

    def test_same_length_corruption_is_rejected_and_partial_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'byte verification failed'):
                download(fixture(b'abcd'),tmp,credential=lambda:'CPU_FIXTURE',open_url=lambda *a,**k:io.BytesIO(b'abce'))
            self.assertFalse(list(Path(tmp).iterdir()))

    def test_oversized_response_is_rejected_before_finalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'larger than'):
                download(fixture(b'abcd'),tmp,credential=lambda:'CPU_FIXTURE',open_url=lambda *a,**k:io.BytesIO(b'abcde'))
            self.assertFalse(list(Path(tmp).iterdir()))

    def test_traversal_duplicate_and_unbound_blob_are_rejected(self):
        for change in ('traversal','duplicate','blob'):
            spec=fixture()
            if change=='traversal':spec['files'][0]['name']='../config.json'
            elif change=='duplicate':spec['files']*=2
            else:spec['files'][0]['blob']='unbound/config.json'
            with self.subTest(change=change),self.assertRaises(ValueError):validate_spec(spec)

    def test_existing_file_is_preserved_without_remote_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'config.json';file.write_bytes(b'EXISTING_DATA')
            with self.assertRaisesRegex(ValueError,'overwrite'),patch('urllib.request.urlopen') as remote:
                download(fixture(),tmp,credential=lambda:'CPU_FIXTURE')
                remote.assert_not_called()
            self.assertEqual(file.read_bytes(),b'EXISTING_DATA')
