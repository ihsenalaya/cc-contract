# Offline HDSC evidence review

This procedure is local and does not start CUDA, contact the VM or authorize GPU
allocation. It distinguishes public-summary consistency from verification of
complete private originals.

## Public artifacts

The immutable result publication is commit
`f179ce927ca803b3fb6da1cd28464f0007646ad5`. Its
[manifest](../../results/manifests/hdsc-final-evaluation-result.json) records
433 executed schedule jobs, 720 unsupported rows and two additional development
controls. The [analysis](../../results/manifests/hdsc-final-evaluation-analysis.json)
contains all ten performance pairs. From the repository root:

```sh
python3 - <<'PY'
import hashlib, json
from pathlib import Path
p = Path('results/manifests')
m = json.loads((p / 'hdsc-final-evaluation-result.json').read_text())
a_path = Path(m['audit']['public_file'])
assert hashlib.sha256(a_path.read_bytes()).hexdigest() == m['audit']['sha256']
a = json.loads(a_path.read_text())
assert a['recorded_jobs'] == a['executed_jobs'] + a['unsupported_not_executed_jobs'] == 1153
assert a['missing_jobs'] == 0
assert a['executed_jobs'] == 433
assert a['independently_verified_development_graph_controls'] == 2
assert len(a['RQ4']['paired_block_metrics']) == 10
assert a['RQ4']['invalid_blocks'] == []
print('Public artifact integrity and count consistency verified; raw evidence not reaudited')
PY
```

This proves internal artifact consistency, not the authenticity of GPU execution.
The manifest's image/source/plan identities must accompany any interpretation.
Per-block percentage = 100 × (ON − OFF)/OFF where OFF is nonzero. The result
manifest supplies those ratios as well as the ratio of block means. Absolute
bootstrap effects can be recomputed using `cc_contract.hdsc_statistics.paired_effect`
with its published seed and 2,000 draws; ten blocks are the units.

## Complete originals, with authorized private access

Obtain the final AI archive, its `collection.json`, the recovered native archive
and collection, and the approved AI-only `plan.json` from the evidence owner.
Compare archive SHA-256 values with the public section provenance. Extract only
regular files beneath a new private directory: reject absolute paths, `..`, links
and special files. Verify every extracted file against its collection map before
analysis. Keep the two archive origins separate.

Construct a new private directory with these verified inputs:

```text
assembled/
  core/jobs.jsonl       # 1010b original core prefix, exactly as collected
  core/summary.json     # 1010b original core summary
  ai/jobs.jsonl         # 1010d original AI records
  ai/summary.json       # 1010d original AI summary
  ai/development-OFF.json
  ai/development-ON.json
```

The full extracted AI directory can be used; retain its other files. Do not copy
failed AI records from 1010b or any execution from the excluded 1010a attempt into
the assembled evidence. The expected core-prefix hash is plan-bound. Retain the
plan unchanged, with SHA-256
`fc992fd61490766db9a7c5abd516f715dc8f5726468f397df6b1314f0bed887b`.

From a checkout of executable source
`7a90394807436945c419fd0271410ddecd413844`, use private input/output paths:

```sh
PYTHONPATH=src python3 scripts/analyze-hdsc-evaluation.py \
  /protected/assembled \
  --plan /protected/plan.json \
  --schedule experiments/hdsc-schedule-v1.json \
  --output /protected/new-analysis.json
```

The output path must not already exist. The analyzer verifies disjoint section
provenance, exact schedule membership, rejected-tool evidence, native arithmetic,
state witnesses, model argmaxes and full development logits. Compare the new
analysis bytes with the published SHA-256. Preserve discrepancies and their
inputs; do not edit originals until an audit passes. Hash agreement does not
provide a new hardware attestation or independent laboratory replication.

The retained H100 is unnecessary for these checks. New GPU execution requires
fresh explicit approval of a separately costed plan.
