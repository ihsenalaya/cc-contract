# Sequential development sample v1

This diagnostic measures the existing end-to-end IR search pipeline on one
confidential H100. Only one campaign is active at a time. It changes neither
the reserved 140-job E4/E5 schedule nor its 20 blocks and 600-second budgets.

The predeclared sample has two development blocks, all seven methods per
block, and 60 seconds per method: fourteen successive jobs and 840 seconds
(14 minutes) of campaign budgets. The order is randomized before execution
with seed 9100901. The resulting seeds are distinct from the reserved seeds.
Configurations use `block: null`, a separate `sample_block`, and partition
`development_sequential_throughput_pilot`. They cannot be counted as reserved
confirmatory blocks. Invalid proposals remain rejected before CUDA.

The existing locally built, Kind-qualified IR image and source remain pinned:
`ghcr.io/ihsenalaya/cc-contract-ir@sha256:e09597869dab698d082cc56ceb5cbb7c6eb348760e08f617387491837ad1fc8a`,
source `1f62b1838196e495d715c1cf063b03ea777aaa94`. A new, separately hash-bound
Python harness is mounted read-only. It uses one persistent native executor
and never runs overlapping campaigns. The runner's original case bytes and
search policy order are preserved. Host qualification precedes the sample:
qualified kernel/driver, CC production, secure boot, attestation command gates,
54 CUDA reference observations, and 96 T01-T08 IR cases.

Record each job's original scenarios, payload/generation observations, invalid
proposals, PASS/FAIL/UNSUPPORTED/infrastructure counts, candidate draws,
coverage, original byte count, and actual wall-clock duration. Report executed
passing cases per actual campaign second, including generation, validation,
IPC, serialization and durable writes. Report both development blocks
individually and their range; these two observations do not justify a stable
variance estimate, power calculation or superiority claim.

The user prioritizes total elapsed time. Measure separately:

- Local preparation and qualification, with the first observed preparation
  timestamp identified rather than inventing a start time.
- The cloud cycle, from immediately before Terraform apply through VM creation,
  image pulls, host checks, the fourteen jobs, evidence export, and confirmed
  deallocation. The deallocation timestamp defines the end of GPU waiting.
- Temporary-resource destruction, CPU-only independent review and Azure backup.
- Waiting for user approval/decision; it is not GPU execution time.

Keep original monotonic and UTC job intervals, host command timings, controller
phase events and run-start/run-exit receipts. Report actual durations and any
unfinished phases. Provisioning and export overhead must remain visible when
estimating another campaign. Actual billing is separate from retail estimates.

Stop after a candidate failure, unsupported case, infrastructure error, signal,
or resource limit, preserving complete original records. The trace limit is
256 MiB per job with at most one complete-record overshoot, and the free-space
reserve is 2 GiB. A last case can finish beyond its nominal minute; report its
actual duration. The sample container has a 1,200-second outer timeout. A
resource-limited or interrupted run is partial and is never counted as a full
sample. Do not start the next method after such a stop.

After hash-verified evidence export, deallocate immediately; independently audit
every original case locally against the deferred integer/generation reference
and original seeded search order. Review hashes, counts, intervals and provenance
as well as values. The cloud expiry remains independent of the local process.
No model weights, Torch image, MIG, MPS, GPU reset or driver change is needed.

This sample can characterize throughput and operational overhead. It cannot
establish rare-defect detection power or a shorter statistically sufficient
comparison budget. The full schedule still represents 23 h 20 of fixed campaign
budgets, plus measured overhead. Any proposed shorter schedule needs a versioned
scientific justification and user approval before reserved comparisons.
