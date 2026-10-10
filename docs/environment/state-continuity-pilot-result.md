# State-continuity pilot v0.1 — real H100 result

**The 50 serial executions completed and passed independent offline audit.
All 40 injected wrong-state executions returned CUDA success and were detected;
all 10 healthy executions passed. The VM is deallocated and its disk retained.**

This answers the bounded mechanism question positively: the instrumented consumer
actually read a different identity/generation/payload from its trusted host
contract while CUDA completed successfully. These are controlled injected faults,
not discovered NVIDIA vulnerabilities, new field defects, or evidence of B4
superiority over B3. No further H100 use is authorized by this completed window.

## Observed outcomes

| Fault | Runs | Activated | CUDA success | Detected | Missed |
|---|---:|---:|---:|---:|---:|
| HEALTHY | 10 | 0 | 10 | 0 | 0 |
| L1 — synchronization dependency | 10 | 10 | 10 | 10 | 0 |
| L2 — stale captured graph pointer | 10 | 10 | 10 | 10 | 0 |
| C1 — stale generation | 10 | 10 | 10 | 10 | 0 |
| C2 — wrong compatible buffer | 10 | 10 | 10 | 10 | 0 |

Healthy false positives: **0/10**. CUDA errors, invalid observations,
infrastructure failures, unsupported runs and unactivated injections: **0**.

Every consumer expected **A/g2**. The actual device output was **A/g1** for
L1, L2 and C1, **B/g2** for C2, and **A/g2** for HEALTHY. Buffer IDs 1 and 2
encode A and B. The device emitted the bytes it consumed and a sum computed
from those same payload words. The detector compared them with the trusted
contract without receiving the injection flag. The separate auditor imported
neither detector nor injector and recomputed all 50 raw observations, payload
hashes, sums, classifications, activation claims and schedule positions.

L1 is explicitly `ADAPTED_FROM_PUBLISHED_SYNCHRONIZATION_FAULT`: a wrong event
and a controlled consumer-before-late-transfer schedule, not MUTGPU's identical
intra-kernel barrier removal. L2 is `DOCUMENTATION_BACKED_BEHAVIOR` with two
immutable live snapshots, not an NVIDIA bug. C1 and C2 remain proposed
CC-Contract fault models. [Exact sources and adaptations](../methodology/state-continuity-fault-models-v0.1.md).

## Measured time and cost boundary

| Measurement | Observed value |
|---|---:|
| VM start request, UTC | 2026-10-10 16:48:26.844002 |
| Deallocation confirmed, UTC | 2026-10-10 16:52:42.934647 |
| Complete request-to-deallocation interval | **256.090645 s — 4 min 16 s** |
| Fifty-run harness wall time | **47.156502532 s** |
| Docker command interval, including startup/teardown | 51.291348351 s |
| Approved planning ceiling | 30 min / USD 5 |

No time spent preparing, fixing the initial API request, auditing or publishing
on the local CPU is added to VM time. Billing start and the actual invoice were
not measured. The retail rate used for planning was USD 6.98/h; the interval
above is not a claim about Azure's billed duration.

| Scenario | Mean worker wall time (s) | Mean host detector time (µs) |
|---|---:|---:|
| HEALTHY | 0.935027 | 39.5210 |
| L1 | 0.973934 | 47.7714 |
| L2 | 0.933926 | 39.2510 |
| C1 | 0.936796 | 38.6910 |
| C2 | 0.934332 | 45.8612 |

Worker wall time includes process startup, CUDA context setup, transfers and
cleanup; it is not kernel latency. Host detector time measures only the host
comparison. **Total GPU instrumentation overhead remains unmeasured** as
predeclared; there was no uninstrumented paired timing experiment.

## Reproducibility and release evidence

- [All 50 derived run records](state-continuity-pilot-tables/runs.csv), including seeds, expected/observed tags and actual host/image provenance.
- [Per-fault metrics](state-continuity-pilot-tables/faults.csv).
- [Machine-readable result and original proof hashes](../../results/manifests/state-continuity-gpu-result.json).
- [Frozen protocol](../methodology/state-continuity-pilot-v0.1.md) and [50-run schedule](../../experiments/state-continuity-schedule-v0.1.json).

Scientific image source: `ddff8775705a85c278d208b1ba504d18226b7551`.
Controller source: `d5ae2d7ebb14796a2d4c7e44a64f4c0d2fb4f4e7`.
Executed image:

```text
ghcr.io/ihsenalaya/cc-contract-continuity@sha256:fd60712704b01ca33988aa2734fc0da8cc7c0041eb57669c9237be87df9cc068
```

Actual host: NVIDIA H100 NVL; driver **595.91.07**;
kernel **6.8.0-1066-azure-fde**; **CC ON / PRODUCTION**; **Secure Boot enabled**.
This pilot did not independently verify GPU attestation or establish full E0.
The existing VM UUID and OS disk identity were preserved. Nothing was destroyed.
The original archive contains 15 hash-verified files, 12,066 compressed bytes:
`dc9ad97597562a026a6a22547beec08cd1fa5efc2574736bff5e7276fb49d0f6`.
Original evidence and the independent audit/lifecycle receipts are backed up in
private Azure storage. Full remote downloads matched their SHA-256 hashes
([backup receipt](../../results/manifests/state-continuity-gpu-backup.json)).
Published CSV files are derived records.

The initial guard renewal used unsupported PATCH semantics and was rejected
before any VM start request (INC-0113). The local correction used PUT on the
same workflow, preserved its identity/configuration and checked the readback.
The scientific image, 50 runs, VM identity, 30-minute allowance and USD 5 budget
were unchanged. There was one actual VM start, not a second paid GPU sample.

## Decision and limits

**GO for mechanism feasibility on these four bounded fault models.** All
predeclared technical gates and the four-model activation checks passed.
This permits preparing a separate random/B3/B4 comparison; it does not authorize
another H100 window. [Next comparison design, not frozen](../methodology/state-continuity-comparison-v0.1-draft.md).

Ten repetitions per deterministic fault do not establish statistical superiority,
field detection rates or a general low false-positive rate. The host contract and
consumer instrumentation are trusted, and the observer does not cover arbitrary
uninstrumented kernels or malicious self-consistent forged observations.
The 140 historical jobs, their 14,000 selected cases, E4/E5 results, original
archives, manifests and hashes remain unchanged in their separate baseline.
