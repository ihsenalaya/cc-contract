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

The real cloud lifecycle, confidential-image/verifier compatibility, expiration
and H100 destroy/recreate qualification remain unvalidated. These require the
approved first window; see the costed proposal in docs/environment. Reviewers without Azure H100 access can reproduce only local model checks.
Sensitive attestation reports, cloud identifiers and nonredistributable model
weights must remain protected; sanitize and hash shared evidence.
