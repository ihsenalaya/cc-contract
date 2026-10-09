import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch


spec=importlib.util.spec_from_file_location('artifact_upload',Path(__file__).resolve().parents[2]/'scripts/azure-artifacts.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ArtifactUploadTests(unittest.TestCase):
    def test_empty_original_is_a_direct_zero_byte_block_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            original=Path(directory)/'empty.stderr';original.write_bytes(b'')
            digest=hashlib.sha256(b'').hexdigest()
            with patch.object(module,'request',return_value=MagicMock()) as request:
                module.upload_blocks('account','evidence','object',original,digest)
            request.assert_called_once_with('account','evidence','object',method='PUT',data=b'',headers={
                'x-ms-blob-type':'BlockBlob','x-ms-meta-sha256':digest,'If-None-Match':'*'})
            self.assertEqual(original.read_bytes(),b'')

    def test_nonempty_original_still_commits_exact_ordered_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            original=Path(directory)/'original';original.write_bytes(b'abcdefg')
            with patch.object(module,'BLOCK_SIZE',3),patch.object(module,'request',return_value=MagicMock()) as request:
                module.upload_blocks('account','evidence','object',original,hashlib.sha256(b'abcdefg').hexdigest())
            blocks=[call.kwargs['data'] for call in request.call_args_list if call.kwargs.get('query',{}).get('comp')=='block']
            self.assertCountEqual(blocks,[b'abc',b'def',b'g'])
            commit=request.call_args_list[-1]
            self.assertEqual(commit.kwargs['query'],{'comp':'blocklist'})
            self.assertEqual(commit.kwargs['data'],b'<BlockList><Latest>MDAwMDAwMDA=</Latest><Latest>MDAwMDAwMDE=</Latest><Latest>MDAwMDAwMDI=</Latest></BlockList>')
            self.assertEqual(original.read_bytes(),b'abcdefg')


if __name__=='__main__':unittest.main()
