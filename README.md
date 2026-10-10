# CC-Contract

Experimental software for **Runtime Semantic State-Continuity Verification for Confidential GPU Execution**. Historical stateful-testing campaigns remain separately documented.

This repository implements and records experiments; it is not a paper manuscript.
Latest checkpoint: the [140-job H100 campaign](docs/environment/fixed-work-campaign-result.md)
is independently audited and published. Its retained VM is deallocated.
The separate [state-continuity pilot](docs/environment/state-continuity-pilot-result.md)
completed 50 real H100 runs: 40/40 injected divergences detected with CUDA
success and 0/10 healthy alerts. Its complete VM window was 4 min 16 s;
the VM is deallocated, and any further H100 use requires fresh approval.
The implementation includes a CPU model, conservative sequence validator,
integer/metadata oracles, CUDA adapters and local Kubernetes qualification.
No CPU result establishes CUDA correctness, GPU attestation or method superiority.
Historically, the first approved real H100 window completed 54 bounded CUDA observations with
independently checked integer arrays, CPU token signature review and local GPU
hardware-verifier receipts. All 13 temporary resources were destroyed. E0 remains
partial. Later inference and campaign results are tracked in
[experiment status](experiments/status.json); actual independent expiry and
full recreation claims remain unvalidated.

## Runtime semantic state-continuity study (HDSC v1)

The new study is scoped in [three scientific contributions](docs/paper/scientific-contribution.md)
and the [related-work matrix](docs/paper/related-work-matrix.md). Its CPU development
checks are [independently audited](results/manifests/hdsc-development-qualification.json):
24/24 injected state violations detected, 0/24 healthy alerts, 47 dynamic sequences,
and four fault pairs on a real pretrained TinyStories Transformer. These are not
RQ2–RQ4 GPU results or evidence of general superiority. Historical GPU campaigns
are preserved separately.

The approved [reduced H100 window](docs/environment/hdsc-resumption-plan.md)
completed **363 native jobs**, independently audited and privately backed up:
[results and remaining work](docs/environment/hdsc-resumption-result.md).
CC-Contract detected 120/120 injected RQ2 violations, including 80 with unchanged
final output; 120 paired healthy runs had no alert. Native dynamic runs detected
40/40 injections, with no alerts on ten dynamic and 70 additional healthy runs.
These are controlled benchmark results, not evidence of discovered real bugs.
Compute Sanitizer rejected the CC configuration; 720 dependent records were
explicitly skipped and cannot support a sanitizer comparison.

The Transformer phase failed after its image downloaded; its exact cause remains
unconfirmed pending recovery of final guest logs. **70 AI jobs remain unvalidated**,
including the overhead experiment. The VM is **deallocated**, with disk retained;
the complete start-to-release interval was **13 min 12 s**. The earlier
[interrupted attempt](docs/environment/hdsc-interrupted-window.md) was recovered
and excluded as a whole; exposed inputs must not be called an unseen holdout.
Follow the [checkpoint journal](docs/research/hourly-progress.md). Any further
restart requires a fresh approved plan; local analysis and publication continue.

Reproduce CPU-only native development checks without model downloads:

```sh
PYTHONPATH=src python3 scripts/qualify-hdsc-local.py --output PRIVATE_NEW_DIRECTORY
```

For trained-model checks, download the seven pinned, hash-verified files with
`scripts/prepare-hdsc-model.py --output PRIVATE_MODEL_DIRECTORY`, then use
`qualify-hdsc-local.py --model PRIVATE_MODEL_DIRECTORY` in the qualified AI image
or an isolated PyTorch 2.8 / Transformers 4.57.1 environment. No raw logits or
model weights belong in Git. The immutable images and final qualification receipt
are recorded with the frozen plan.

## Reproduce the initial checks

Python 3.10+ and Git are required. The runner has no third-party runtime dependencies.
Source tests and the independent CPU attestation reviewer require the pinned
dependencies in `scripts/requirements-review.txt`.

```sh
bash scripts/quick-check.sh
PYTHONPATH=src python3 -m cc_contract.cli selftest --output .local/runs
PYTHONPATH=src python3 -m cc_contract.cli corpus
bash scripts/kind.sh create
bash scripts/kind.sh check
```

The first corpus belongs to oracle development. Controlled mutants are injected
only into the CPU observation adapter, never into a GPU memory race. The runner
checks that their expected FAIL verdicts are produced; they are not discoveries.
Invalid sequences are rejected before the execution adapter is invoked.

See [verified local checkpoint](docs/environment/local-checkpoint.md),
[first real H100 result](docs/environment/first-gpu-result.md),
[first GPU window proposal](docs/environment/first-gpu-window.md),
[reproducibility](docs/reproducibility/README.md),
[protocol and gates](docs/methodology/protocol.md),
[experiment status](experiments/status.json), and
[incident history](docs/incidents/incidents.jsonl).

Infrastructure automation has both initial create/qualify/collect/release evidence
and retained-VM campaign evidence. The current VM, disk and restart resources
are preserved; no restart or further H100 use is authorized by a completed window.
