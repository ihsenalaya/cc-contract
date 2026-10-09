"""Storage transport guards, using small local fixtures only."""
import importlib.util
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('artifacts', ROOT/'scripts/azure-artifacts.py')
artifacts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifacts)


class ArtifactStoreTests(unittest.TestCase):
    def test_blocks_reconstruct_exact_source_before_immutable_commit(self):
        stored={};commits=[]
        def endpoint(account,container,blob,method,data,query,headers):
            if query['comp']=='block':
                self.assertEqual(headers['Content-MD5'],base64.b64encode(hashlib.md5(data).digest()).decode())
                stored[query['blockid']]=data
            else:
                self.assertEqual(headers['If-None-Match'],'*')
                commits.append(b''.join(stored[node.text] for node in ET.fromstring(data)))
            return io.BytesIO()
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'fixture';source.write_bytes(bytes(range(256))*3)
            with patch.object(artifacts,'BLOCK_SIZE',100),patch.object(artifacts,'request',side_effect=endpoint),patch('sys.stdout',new_callable=io.StringIO):
                artifacts.upload_blocks('fixture','models','fixture',source,artifacts.sha(source))
            self.assertEqual(commits,[source.read_bytes()])

    def test_failed_block_never_commits_partial_blob(self):
        committed=[]
        def endpoint(account,container,blob,method,data,query,headers):
            if query['comp']=='blocklist':committed.append(True)
            raise RuntimeError('CONTROLLED_TRANSPORT_FAILURE')
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'fixture';source.write_bytes(b'CPU_FIXTURE')
            with patch.object(artifacts,'request',side_effect=endpoint):
                with self.assertRaisesRegex(RuntimeError,'CONTROLLED_TRANSPORT_FAILURE'):
                    artifacts.upload_blocks('fixture','models','fixture',source,artifacts.sha(source))
            self.assertFalse(committed);self.assertTrue(source.exists())

    def test_windows_cli_receives_valid_unc_path_without_copying(self):
        with patch.object(artifacts.shutil, 'which', return_value='/mnt/c/Azure/az'), patch.dict(os.environ, {'WSL_DISTRO_NAME':'Ubuntu-22.04'}):
            self.assertEqual(artifacts.windows_path('/home/fixture/model'), r'\\wsl.localhost\Ubuntu-22.04\home\fixture\model')

    def test_wrong_remote_bytes_never_produce_verified_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp); source=state/'fixture';source.write_bytes(b'LOCAL_FIXTURE')
            (state/'outputs.json').write_text(json.dumps({'account_name':{'value':'fixture'}}))
            with patch.object(artifacts,'STATE',state), patch.object(artifacts,'blob_exists',return_value=True), patch.object(artifacts,'remote_hash',return_value=('0'*64,source.stat().st_size)), patch('sys.stdout',new_callable=io.StringIO):
                with self.assertRaisesRegex(RuntimeError,'Remote byte verification failed'):
                    artifacts.upload([source],'models','receipt.json')
            self.assertTrue(source.exists()); self.assertFalse((state/'receipt.json').exists())

    def test_unverified_previous_record_cannot_skip_remote_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);source=state/'fixture';source.write_bytes(b'LOCAL_FIXTURE')
            (state/'outputs.json').write_text(json.dumps({'account_name':{'value':'fixture'}}))
            (state/'receipt.json').write_text(json.dumps({'files':[{'local_path':str(source),'sha256':artifacts.sha(source),'remote_bytes_verified':False}]}))
            with patch.object(artifacts,'STATE',state), patch.object(artifacts,'blob_exists',return_value=True), patch.object(artifacts,'remote_hash',return_value=(artifacts.sha(source),source.stat().st_size)) as remote, patch('sys.stdout',new_callable=io.StringIO):
                artifacts.upload([source],'models','receipt.json')
                remote.assert_called_once()

    def test_symlink_is_rejected_before_reading_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);source=state/'fixture';source.write_bytes(b'LOCAL_FIXTURE');link=state/'link';link.symlink_to(source)
            (state/'outputs.json').write_text(json.dumps({'account_name':{'value':'fixture'}}))
            with patch.object(artifacts,'STATE',state):
                with self.assertRaisesRegex(ValueError,'regular project files'):
                    artifacts.upload([link],'models','receipt.json')
