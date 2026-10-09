"""Small CPU serialization fixtures; no real model or hardware claims."""
import importlib.util
import io
from pathlib import Path
import pickle
import struct
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('tensor_review', Path(__file__).resolve().parents[2]/'scripts/review-torch-pilot.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def text(value):
    raw = value.encode()
    return b'X'+struct.pack('<I',len(raw))+raw


def metadata():
    # Protocol 2, exactly the declared contiguous float32 CPU tensor layout.
    return (b'\x80\x02ctorch._utils\n_rebuild_tensor_v2\n(('
            +text('storage')+b'ctorch\nFloatStorage\n'+text('0')+text('cpu')
            +b'K\x02tQK\x00(K\x02t(K\x01t\x89ccollections\nOrderedDict\n)RtR.')


def archive(data=None, values=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output,'w') as zip:
        zip.writestr('fixture/data.pkl', metadata() if data is None else data)
        zip.writestr('fixture/byteorder',b'little')
        zip.writestr('fixture/data/0',struct.pack('<ff',1.,-2.) if values is None else values)
    return output.getvalue()


class Trigger:
    def __reduce__(self):
        return eval, ('1/0',)


class TensorArtifactTests(unittest.TestCase):
    def test_known_layout_decodes_and_truncated_storage_is_rejected(self):
        tensor = review.read_tensors(archive())
        self.assertEqual(tensor.shape,(2,))
        self.assertEqual(tensor.data,(1.,-2.))
        self.assertEqual(tensor.kind,'f')
        with self.assertRaisesRegex(ValueError,'byte count'):
            review.read_tensors(archive(values=struct.pack('<f',1.)))

    def test_nonfinite_tensor_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Nonfinite'):
            review.read_tensors(archive(values=struct.pack('<ff',1.,float('nan'))))

    def test_unexpected_pickle_callable_is_rejected_without_execution(self):
        with self.assertRaisesRegex(ValueError,'Unexpected serialized global'):
            review.read_tensors(archive(data=pickle.dumps(Trigger(),protocol=2)))


if __name__ == '__main__':
    unittest.main()
