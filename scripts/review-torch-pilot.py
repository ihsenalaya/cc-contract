"""Audit original pilot tensors and numerical records without installing Torch.

This is an offline consistency/reference audit, not absolute model correctness
or independent hardware attestation. Only contiguous CPU float32/int64 tensor
artifacts from the declared serialization layout are accepted.
"""
import argparse
from collections import OrderedDict
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import io
import json
import math
from pathlib import Path
import pickle
import pickletools
import struct
import tarfile
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Tensor:
    def __init__(self, data, shape, kind):
        self.data, self.shape, self.kind = data, tuple(shape), kind


def rebuild(storage, offset, size, stride, requires_grad, hooks, *metadata):
    kind, values = storage
    require(not requires_grad and not hooks and not metadata, 'Unexpected tensor metadata')
    require(type(offset) is int and offset >= 0 and len(size) <= 2, 'Invalid tensor dimensions')
    require(all(type(n) is int and 0 < n <= 2_000_000 for n in size), 'Invalid tensor size')
    require(len(size) == len(stride), 'Invalid tensor stride')
    expected = 1
    for n, step in zip(reversed(size), reversed(stride)):
        require(step == expected, 'Only contiguous tensors accepted')
        expected *= n
    require(offset + expected <= len(values), 'Tensor storage overrun')
    return Tensor(values[offset:offset+expected], size, kind)


class TensorReader(pickle.Unpickler):
    def __init__(self, data, archive, prefix):
        super().__init__(io.BytesIO(data))
        self.archive, self.prefix, self.cache = archive, prefix, {}

    def find_class(self, module, name):
        allowed = {('torch._utils', '_rebuild_tensor_v2'): rebuild,
                   ('torch', 'FloatStorage'): 'f', ('torch', 'LongStorage'): 'q',
                   ('collections', 'OrderedDict'): OrderedDict}
        require((module, name) in allowed, 'Unexpected serialized global')
        return allowed[(module, name)]

    def persistent_load(self, pid):
        require(isinstance(pid, tuple) and len(pid) == 5, 'Invalid storage reference')
        label, kind, key, location, count = pid
        require(label == 'storage' and kind in ('f', 'q') and location == 'cpu', 'Unexpected storage type/device')
        require(isinstance(key, str) and key.isascii() and key.isdigit(), 'Invalid storage key')
        require(type(count) is int and 0 < count <= 2_000_000, 'Oversized tensor storage')
        if key not in self.cache:
            member = self.archive.getinfo(self.prefix+'/data/'+key)
            require(member.file_size == count * struct.calcsize(kind), 'Storage byte count mismatch')
            values = struct.unpack('<'+kind*count, self.archive.read(member))
            require(kind == 'q' or all(math.isfinite(v) for v in values), 'Nonfinite tensor values')
            self.cache[key] = (kind, values)
        require(self.cache[key][0] == kind and len(self.cache[key][1]) == count, 'Conflicting storage reference')
        return self.cache[key]


def read_tensors(raw):
    require(len(raw) <= 32*2**20, 'Oversized tensor artifact')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and len(names) <= 100, 'Duplicate/excessive tensor ZIP members')
        require(all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in names), 'Unsafe tensor ZIP pathname')
        entries = [n for n in names if n.endswith('/data.pkl')]
        require(len(entries) == 1, 'Missing tensor metadata')
        prefix = entries[0].rsplit('/', 1)[0]
        require(archive.read(prefix+'/byteorder') == b'little', 'Unexpected tensor byte order')
        require(archive.getinfo(entries[0]).file_size <= 65536, 'Oversized tensor metadata')
        data = archive.read(entries[0])
        blocked = {'BUILD', 'INST', 'OBJ', 'NEWOBJ', 'NEWOBJ_EX', 'EXT1', 'EXT2', 'EXT4'}
        require(not any(op.name in blocked for op, _, _ in pickletools.genops(data)), 'Unsupported pickle object construction')
        return TensorReader(data, archive, prefix).load()


def matrix(value, rows, columns):
    require(isinstance(value, list) and len(value) == rows and all(isinstance(r, list) and len(r) == columns for r in value), 'Numerical matrix shape mismatch')
    require(all(type(v) in (int, float) and math.isfinite(v) for r in value for v in r), 'Nonfinite numerical matrix')


def attention_reference():
    # Rational inputs and a separate higher-precision mathematical evaluation.
    with localcontext() as context:
        context.prec = 100
        q = [[Decimal((i*3+j*7)%11-5)/32 for j in range(8)] for i in range(4)]
        k = [[Decimal((i*5+j*3)%13-6)/32 for j in range(8)] for i in range(4)]
        v = [[Decimal((i*7+j*5)%17-8)/16 for j in range(8)] for i in range(4)]
        result = []
        for row in q:
            scores = [sum(a*b for a,b in zip(row,key))/Decimal(8).sqrt() for key in k]
            exps = [(s-max(scores)).exp() for s in scores]
            total = sum(exps)
            result.append([float(sum(e*values[j] for e,values in zip(exps,v))/total) for j in range(8)])
        return result


def review_components(result):
    env = result['environment']
    require(env['scope'] == 'REAL_TORCH_CUDA' and env['gpu_executed'] is True and env['tf32'] is False and env['deterministic_algorithms'] is True, 'Unqualified numerical environment')
    planned = {(c,r,a) for c in ('tokens_embedding_metadata','linear','reduced_attention') for r in range(3) for a in (False,True)}
    seen = set(); linear_error = 0.; attention_error = 0.
    reference = attention_reference(); u = 2.**-24
    g16 = 16*u/(1-16*u); g8 = 8*u/(1-8*u)
    attention_bound = .5*(2*(g16*8*(6/32)**2/math.sqrt(8)+2*u)+16*u+2*g8)+g8*.5
    for row in result['records']:
        identity = row['component'],row['repeat'],row['asynchronous']
        require(identity in planned and identity not in seen, 'Duplicate/unplanned component')
        seen.add(identity); require(row['verdict'] == 'PASS', 'Component did not pass')
        if row['component'] == 'tokens_embedding_metadata':
            expected = [[float(Fraction(i*8+j,16)) for j in range(8)] for i in (0,3,7,15,3,1,9,0)]
            require(row['observed'] == expected and row['expected'] == expected, 'Embedding contradicts independent reference')
            require(row['expected_generation'] == row['observed_generation'] == row['repeat'], 'Generation mismatch')
        elif row['component'] == 'linear':
            matrix(row['observed'],4,8); require(len(row['oracles']) == 32, 'Missing dot-product records')
            for i in range(4):
                for j in range(8):
                    products = [Fraction(((i*7+t*3)%17-8)*((j*5+t*11)%19-9),256) for t in range(32)]
                    exact = float(sum(products)); magnitude = float(sum(abs(v) for v in products))
                    n = 66; bound = n*u/(1-n*u)*magnitude+n*2.**-149+n*2.**-52*magnitude
                    error = abs(row['observed'][i][j]-exact); claimed = row['oracles'][i*8+j]
                    require(error <= bound and claimed['verdict'] == 'PASS', 'Dot product exceeds predeclared bound')
                    require(claimed['reference'] == exact and claimed['absolute_error'] == error and claimed['bound'] == bound, 'Dot-product diagnostic contradicts raw values')
                    linear_error = max(linear_error,error)
        else:
            matrix(row['observed'],4,8)
            require(row['expected'] == reference and row['bound'] == attention_bound, 'Attention reference/bound changed')
            error = max(abs(a-b) for actual,expected in zip(row['observed'],reference) for a,b in zip(actual,expected))
            require(error <= attention_bound and row['maximum_absolute_error'] == error, 'Attention exceeds predeclared bound or diagnostic is wrong')
            attention_error = max(attention_error,error)
    require(seen == planned and result['verdict'] == 'PASS', 'Incomplete component qualification')
    return {'verdict':'PASS','records':18,'independent_reference_recomputation':True,
            'linear_maximum_absolute_error':linear_error,'attention_maximum_absolute_error':attention_error,
            'attention_predeclared_bound':attention_bound,'torch_version':env['torch_version'],
            'compiled_cuda':env['compiled_cuda'],'independent_campaigns':1}


def review(directory, corpus_path):
    receipt = json.loads((directory/'collection.json').read_text())
    source = directory/receipt['archive_file']
    require(hashlib.sha256(source.read_bytes()).hexdigest() == receipt['archive_sha256'], 'Original archive changed')
    bundle = json.loads((directory/'workload-bundle.json').read_text())
    corpus_raw = corpus_path.read_bytes()
    require(hashlib.sha256(corpus_raw).hexdigest() == bundle['corpus_sha256'], 'Frozen corpus changed')
    corpus = json.loads(corpus_raw); require(len(corpus) == 24, 'Incomplete frozen corpus')
    with tarfile.open(source) as archive:
        def read(name):
            member = archive.getmember('cc-contract-evidence/'+name)
            require(member.isfile(), 'Unexpected evidence member type')
            return archive.extractfile(member).read()
        component_data = json.loads(read('pytorch-components.stdout'))
        require(component_data['image_digest'] == bundle['images']['torch'], 'Component image changed')
        components = review_components(component_data)
        manifest = json.loads(read('inference/run/manifest.json'))
        raw = read('inference/run/records.jsonl')
        require(hashlib.sha256(raw).hexdigest() == manifest['raw_sha256'], 'Inference record hash mismatch')
        require(manifest['image_digest'] == bundle['images']['torch'] and manifest['corpus_sha256'] == bundle['corpus_sha256'], 'Inference provenance changed')
        require(manifest['model']['revision'] == bundle['model_revision'], 'Model revision changed')
        require(manifest['device'] == 'cuda' and manifest['environment']['gpu_executed'] is True, 'Inference did not run on CUDA')
        records = [json.loads(line) for line in raw.splitlines()]
        require(len(records) == manifest['cases'] == 24, 'Incomplete inference corpus')
        steps = 0; elements = 0
        for index,(record,case) in enumerate(zip(records,corpus)):
            require(record['case'] == index and record['run_id'] == manifest['run_id'] and record['seed'] == 17001, 'Inference identity mismatch')
            require(record['length'] == case['length'] and record['metadata_exact'] is True, 'Inference input/metadata mismatch')
            encoded = json.dumps(case['token_ids'],sort_keys=True,separators=(',',':')).encode()+b'\n'
            require(record['input_sha256'] == hashlib.sha256(encoded).hexdigest(), 'Input token hash changed')
            require(len(record['pairs']) == 2, 'Missing paired path')
            tensors = []
            for pair,path in zip(record['pairs'],('sync','async')):
                name = f'case-{index:02d}-{path}.pt'
                require(pair['artifact'] == name and pair['observed_generation'] == index, 'Artifact identity/generation mismatch')
                payload = read('inference/run/'+name)
                require(hashlib.sha256(payload).hexdigest() == pair['sha256'], 'Tensor artifact hash mismatch')
                value = read_tensors(payload)
                expected = tuple(case['token_ids']+case['forced_continuation'])
                require(value['token_ids'].kind == 'q' and value['token_ids'].shape == (1,len(expected)) and value['token_ids'].data == expected, 'Physical input token mismatch')
                require(value['generation'].kind == 'q' and value['generation'].shape == (1,) and value['generation'].data == (index,), 'Physical generation mismatch')
                require(len(value['steps']) == 1+len(case['forced_continuation']), 'Missing inference steps')
                tensors.append(value)
            require(len(record['diagnostics']) == len(tensors[0]['steps']), 'Missing paired diagnostics')
            for left,right,diagnostic in zip(tensors[0]['steps'],tensors[1]['steps'],record['diagnostics']):
                for key in ('logits','hidden'):
                    a,b = left[key],right[key]
                    require(a.kind == b.kind == 'f' and a.shape == b.shape and len(a.shape) == 1, 'Output shape/dtype mismatch')
                    require(a.data == b.data, 'Paired output divergence: requires separate anomaly review')
                    require(diagnostic[key]['verdict'] == 'PASS' and diagnostic[key]['exact_equal'] is True and diagnostic[key]['maximum_absolute_difference'] == 0, 'Diagnostic contradicts raw tensor values')
                    elements += len(a.data)
                steps += 1
        require(manifest['state'] == 'COMPLETE_PAIRED_DIAGNOSTIC' and manifest['verdict'] == 'PASS' and manifest['paired_path_divergences'] == 0, 'Unexpected inference aggregate')
    return {'scope':'OFFLINE_ORIGINAL_GPU_COMPONENT_REFERENCE_AND_PAIRED_TENSOR_AUDIT',
            'archive_sha256':receipt['archive_sha256'],'components':components,
            'inference':{'verdict':'PASS','prompts':24,'paths':48,'paired_steps':steps,
                         'logit_and_hidden_values_compared':elements,'physical_tokens_and_generations_exact':True,
                         'paired_outputs_exact_equal':True,'independent_campaigns':1,
                         'independent_absolute_model_correctness':False},
            'independent_GPU_attestation':'SEPARATE_REQUIRED','scientific_superiority_claim':False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory',required=True,type=Path)
    parser.add_argument('--corpus',required=True,type=Path)
    args = parser.parse_args()
    print(json.dumps(review(args.directory,args.corpus),indent=2))


if __name__ == '__main__':
    main()
