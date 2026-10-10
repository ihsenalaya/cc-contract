# CC-Contract

Experimental software for **Stateful Contract-Guided Testing of Host–Device Data Paths for Confidential GPU Inference**.

This repository implements and records experiments; it is not a paper manuscript.
Latest checkpoint: the [140-job H100 campaign](docs/environment/fixed-work-campaign-result.md)
is independently audited and published. Its retained VM is deallocated.
The separate [state-continuity pilot](docs/environment/state-continuity-pilot-window.md)
has passed CPU/Kind qualification and local CUDA compilation; its proposed
50 real GPU runs require fresh user approval and have not started.
The implementation includes a CPU model, conservative sequence validator,
integer/metadata oracles, CUDA adapters and local Kubernetes qualification.
No CPU result establishes CUDA correctness, GPU attestation or method superiority.
Historically, the first approved real H100 window completed 54 bounded CUDA observations with
independently checked integer arrays, CPU token signature review and local GPU
hardware-verifier receipts. All 13 temporary resources were destroyed. E0 remains
partial. Later inference and campaign results are tracked in
[experiment status](experiments/status.json); actual independent expiry and
full recreation claims remain unvalidated.

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
