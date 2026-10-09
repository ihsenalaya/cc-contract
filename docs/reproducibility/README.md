# Reproducibility and provenance

## Sources and scope

The versioned IR, generator, validator, CPU execution model and oracle are under
src/cc_contract. Run `bash scripts/quick-check.sh` from a clean clone. Each runner
output identifies the simulation scope, source hash, commit, dirty tree, seed,
scenario, expected/observed data and verdict. A manifest links all case records
by Run ID and records a hash of canonical JSONL. Raw files are finalized as
read-only files in unique directories; chmod is a local safeguard, not WORM
storage or a cryptographic signature. Hashes provide integrity, not authorship.

Original logs/results live in .local or a separate protected evidence directory,
outside public Git. Public manifests may include hashes and sanitized summaries.
To verify JSONL, compare `sha256sum records.jsonl` with manifest.raw_sha256.
Do not edit finalized data. Make a new Run ID for a repeated or corrected run.

## Kind

Docker Engine/Desktop running with Linux containers, kind 0.31.0, kubectl 1.35
and Bash are required. The node image is pinned to the digest in the official
[Kind release](https://github.com/kubernetes-sigs/kind/releases/tag/v0.31.0).
Scripts use their own kubeconfig and explicit context; an unrelated cluster is
not modified. The restricted namespace and token-free job have no API rights.
Two indexed job completions must run on distinct CPU workers.

```sh
bash scripts/kind.sh create
bash scripts/local-image.sh build
bash scripts/local-integration.sh
bash scripts/kind.sh collect .local/kind-logs
bash scripts/kind.sh destroy
```

Image build/release procedures and their verified digests are recorded in
results/manifests. This image contains only the CPU model, no CUDA or model
weights. A future GPU image requires its own qualification and manifest.
Builds are local. CI is for source checks and never builds/publishes images.

## Durable Git synchronization

`bash scripts/install-sync.sh` installs a user crontab every two hours, at reboot,
and a five-minute retry for missed/failed synchronization. The active system cron
daemon runs without an open conversation. `bash scripts/sync.sh` performs tests,
an allowlist/credential-pattern check and Trivy secret scanning before committing
permitted artifacts and pushing, without force. Failures are logged in
.local/sync/events.log; >3 h gaps are recorded on the next attempt.

On this Windows/WSL host, `scripts/install-windows-sync.ps1` also installs the
`CCContractGitSync` Windows task. Every five minutes and at user logon it invokes
WSL's retry script; an actual backup runs only when the two-hour checkpoint is due.
This wakes WSL independently of an open conversation. The task runs with the
current logged-on Windows user and limited privileges, without storing a password.
WSL cron remains a second trigger; flock prevents simultaneous backup runs.
The PowerShell launcher passes validated arguments directly to a managed WSL
process, closes its standard input and records its exit status. Distribution,
Linux username and workspace path must contain no spaces or shell metacharacters.
A scheduled invocation completed with exit code 0 while no backup was due;
manual Linux synchronization separately completed checks and a GitHub push.

WSL must be running for its cron daemon to execute. Nothing logs while the host
is powered off. The gap is detected on restart/reconnection; checkpoints resume
with the next retry. The schedule does not authorize any GPU experiments.
No scanner can prove the absence of every possible sensitive value; evidence
must be reviewed before public summaries are added to the allowlist.

## Azure

No H100 has been provisioned during local preparation. Azure quotas and catalog
listings do not guarantee real capacity. Cost estimates must distinguish public
list rates from actual subscription invoices and include startup, qualification,
storage, egress and any CPU control plane. A guest shutdown is insufficient:
the Azure state must be deallocated, as described in
[Azure billing states](https://learn.microsoft.com/azure/virtual-machines/states-billing).

A pinned Terraform module and `scripts/azure-window.py` now implement the first
window: read-only plan, hash-approved apply/run, qualification, verified archive
export, release and destruction. `scripts/cuda-image.sh build|kind|publish` builds
and tests the native E0 probe locally and verifies absence of hardware is reported
as UNSUPPORTED. The CUDA image is separate from the Python CPU model image.

The subsequently approved first real window executed create/qualify/collect/
deallocate/destroy and removed all 13 temporary resources; see
[the result](../environment/first-gpu-result.md). Independent expiry deallocation,
actual H100 recreation and PyTorch/inference qualification remain required.
Reviewers without Azure H100 access can reproduce only local model checks.
Sensitive attestation reports, cloud identifiers and nonredistributable model
weights must remain protected; sanitize and hash shared evidence.

## Independent review of the first GPU archive

Install the pinned source-test/review dependencies in an isolated environment:

```sh
python3 -m venv .local/review-venv
.local/review-venv/bin/pip install -r scripts/requirements-review.txt
PYTHONPATH=src .local/review-venv/bin/python -m unittest discover -s tests/unit
.local/review-venv/bin/python scripts/review-gpu-window.py \
  --directory /home/ihsen/.local/state/cc-contract/e0-20261009b \
  --vm-identity /home/ihsen/.local/state/cc-contract/e0-20261009b/terraform.tfstate.backup.vm-review-snapshot.json
```

The protected archive and VM identity snapshot are required; their original
tokens and machine identifiers are not public Git artifacts. The reviewer checks
archive/file hashes, all expected CUDA observations and arrays, and the CPU
RS256 token using signing keys fetched over verified HTTPS from the fixed MAA
issuer. It binds the CPU VM identity to the Terraform snapshot and checks token
validity at capture time, Secure Boot, SNP compliance and disabled debugging.
Cached keys and each timestamped review remain private; only sanitized summaries
and hashes are published. Run without Python optimization.

GPU receipts came from NVIDIA's local hardware verifier. Their reported checks
are reviewed, but this reviewer does not independently authenticate their HMACs
or reverify an exported hardware quote. It does not claim NRAS attestation.

## Extended local software qualification

The [v0.2 draft](../methodology/protocol-v0.2-draft.md) describes the bounded
eight-family generator, physical native generation tags, baselines, ablations,
reducers and analysis rules. It is not frozen for GPU comparison.

```sh
PYTHONPATH=src python3 -m cc_contract.runner qualify --backend model
bash scripts/ir-image.sh build
bash scripts/ir-image.sh kind
bash scripts/ir-image.sh publish
bash scripts/torch-image.sh build
bash scripts/torch-image.sh kind
bash scripts/torch-image.sh publish
```

The native reference executes the same compiled C++ worker in CPU mode; its
96 cases / 252 observations are distinct from the 60-case initial E1 corpus.
Kind must report CPU scope and reject missing GPUs. CUDA mapped/graph features
require actual capability probes; errors other than explicit unsupported APIs
stop execution. Local native agreement is not hardware qualification.

The PyTorch image is built locally from a digest-pinned official PyTorch base,
with hash-locked Transformers dependency wheels. Component tests use independent
float references. Its tiny random transformer is an API fixture, not Qwen 7B.
Both CPU workers must execute the actual image before GHCR publication. Docker
must be running with sufficient disk space; CPU-only tools remain usable when
Docker is unavailable.

Prepare model data while no GPU is allocated:

```sh
python3 scripts/prepare-model.py download --weights --directory /protected/models/qwen
# Run this inside the qualified PyTorch image, mounting the script and model:
python scripts/prepare-model.py corpus --directory /protected/models/qwen --output /protected/corpus.json
```

The corpus action requires the pinned Transformers/tokenizer environment.
Model revisions, every downloaded file hash, exact token counts and forced
continuation must match. Model files stay outside Git. Upload them before a GPU
test window's measurements; preserve the qualified host driver and kernel.

The versioned 140-job schedule preserves the proposed 20 blocks × seven methods
× 600 seconds. It is a plan, not a record of executed GPU campaigns:

```sh
PYTHONPATH=src python3 scripts/execute-schedule.py \
  --schedule experiments/comparison-schedule.json --backend cuda \
  --protocol-freeze /protected/approved-freeze.json \
  --output /protected/campaigns --start-index 0 --jobs 1
python3 scripts/analyze-campaigns.py /protected/campaigns/campaign-*/manifest.json \
  --output /protected/new-analysis --figures
PYTHONPATH=src python3 scripts/replay-scenario.py --scenario /protected/case.json \
  --backend cuda --reduce contract --budget-seconds 60 --output /protected/new-reduction
```

These GPU commands additionally require CC_IMAGE_DIGEST, hardware qualification,
a frozen matching schedule and a costed approved temporary window. They are
not authorization to allocate a GPU. Use `--resume` on the schedule command to
skip hash-verified complete runs. Interrupted runs remain immutable; they are
reported separately and any replacement budget needs approval. The final
pre-execution validator is retained in every baseline and ablation.

Analysis creates a new directory and verifies raw hashes without changing
originals. It refuses mixed scopes, duplicate block/method units and unequal
budgets. Candidate FAILs are not confirmed defects. An optional separate
`--reviews` JSON registry requires characterized grouping and two hashed fresh
failing replays for each confirmed anchor. Empty reviews cannot establish that
unreviewed failures are false positives. Tokens and within-run repeats are not
independent campaigns. Coverage figures are explicitly software coverage.

E6 and E8 require suitable real characterized anomalies. The E8 callable harness
qualifies conservative/intervention correctness before timing and records paired
blocks. Its unit-test callables are CPU fixtures; they are not measured GPU
interventions. Historical H08/H09 records list missing reproduction prerequisites
in experiments/historical-cases.json.
