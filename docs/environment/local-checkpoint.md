# Local checkpoint — 2026-10-09

This records the initial local qualification before deployment. The subsequent
[first real H100 result](first-gpu-result.md) supersedes its statements about
pending approval and GPU execution. Post-run source checks now pass 24 tests,
including cryptographic and independent-array rejection paths and qualification
exit propagation after cleanup; these added tests remain CPU fixtures.

Verified implementations: bounded sequence legality, exact integer/generation
oracle, development corpus (24 legal / 24 semantic mutants / 12 invalid),
provenance-preserving runner, private evidence collection, image gates, Kind
lifecycle and network scripts, and durable Git synchronization.

17 unit tests pass, including missing-Git provenance, stream synchronization,
pending buffer reuse/free, stale metadata, malformed inputs, missing capabilities,
Windows CLI encoding, failed export release, archive preservation and rejecting
failed attestation commands even when their output contains success text.
The 60 model cases match their predefined expected categories. These are CPU
fixtures and controlled mutants, not real GPU discoveries or superiority evidence.

Kind has one control plane and two CPU workers. The model ran on both workers,
with restricted pod security and no API token or secret read access. The cluster
was destroyed and recreated and its model jobs passed again. Indexed network
jobs verified DNS and bidirectional TCP between distinct workers.

Both CPU and native CUDA qualification images were built locally, tested and
published on GHCR by immutable digest. The CUDA image was compiled for H100
SM90, tested against its CPU reference, and verified to report UNSUPPORTED on
both CPU workers. This is not real CUDA validation. The native E0 program is
separate from the full CC-Contract IR execution adapter, which is still required.

Terraform validation passes; its single mock planning test passes. The actual
authenticated cloud plan is create-only, with no resource deployed. The proposed
first-window budget awaits user approval. Real H100 recreation, attestation,
GPU oracle calibration and statistical comparisons have not run.

Original logs, image inspection, dependency inventory, SBOM and finalized run
records remain outside public Git; sanitized manifests provide hashes and scope.
See [evidence manifest](../../results/manifests/local-infrastructure-qualification.json)
and [incident journal](../incidents/incidents.jsonl). Earlier failures are retained.

Cron is active with two-hour synchronization, reboot catch-up and five-minute
retry. A limited-privilege Windows Scheduled Task is also installed to start WSL
and invoke the retry script every five minutes and at user logon, independently
of any terminal/conversation. A manual invocation completed tests, secret scanning, commit and push;
GitHub CI passed. Actual passage of a full two-hour interval and a powered-off
host recovery cannot be claimed from the initial invocation alone. WSL must be
running for cron to execute, and missed intervals are logged on resumption.
The final PowerShell Windows launcher was invoked by Task Scheduler and completed
with exit code 0 when no backup was due. Earlier command-wrapper failures remain
in the incident journal; a successful no-op trigger is not an end-to-end scheduled
push or a powered-off-host recovery test.

Historical H100 constraints and reported H08/H09 anomalies are recorded in
[historical GPU reports](../incidents/historical-gpu.md). Previous campaign logs
are unavailable here and those anomalies have not been reproduced by this project.
