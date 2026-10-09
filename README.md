# CC-Contract

Experimental software for **Stateful Contract-Guided Testing of Host–Device Data Paths for Confidential GPU Inference**.

This repository implements and records experiments; it is not a paper manuscript.
Current scope: an initial **CPU simulation**, a conservative sequence validator,
exact integer/metadata oracles, a 24 legal / 24 controlled mutant / 12 invalid
development corpus, local Kubernetes qualification infrastructure, a compiled native CUDA E0 probe,
and a planned temporary Azure lifecycle with independent expiry.
No CPU result establishes CUDA correctness, GPU attestation or method superiority.

## Reproduce the initial checks

Python 3.10+ and Git are required. The runner has no third-party runtime dependencies.

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
[first GPU window proposal](docs/environment/first-gpu-window.md),
[reproducibility](docs/reproducibility/README.md),
[protocol and gates](docs/methodology/protocol.md),
[experiment status](experiments/status.json), and
[incident history](docs/incidents/incidents.jsonl).

Infrastructure automation is being qualified. Azure deployment/recreation,
real CUDA, attestation and comparative campaigns remain unvalidated until actual
executions supply evidence. No H100 existed in the inventoried subscription.
