# HDSC v1 — final retained-H100 evaluation window

Status: local workload qualification complete; protocol frozen; **not approved and not executed**. The machine remains
DEALLOCATED. This document specifies a single sequential evaluation; it does not
reuse permission from a previous pilot. The immutable executable plan will be published at
`results/manifests/hdsc-final-h100-plan.json`; its separate SHA-256 receipt is
`results/manifests/hdsc-final-h100-plan-sha256.json`. Neither is an approval.

## Scientific purpose and boundary

RQ1's independently audited 50-run pilot is complete and untouched. This window
addresses RQ2 detection value, RQ3 online dynamic execution and RQ4 application
overhead. The seven-field HDSC model and assumptions are in `docs/paper/`.
The packet benchmark observes the buffer/generation/payload projection; the native
dynamic and Transformer adapters exercise the online relations, trusting their
host-side bindings. Equal-output fault profiles are constructed. Four causes are
not relabelled as 120 distinct real bugs. No reserved outcome has been inspected.

Novelty relative to LGT4CG remains provisional: prepared-metadata verification
substantially overlaps this question, and its complete dynamic scope has not been
established from the available primary material. A successful experiment would
support bounded evidence, not automatically a novel Q1 article.

## Exact inventory and order

`experiments/hdsc-schedule-v1.json` is the complete job inventory. Every row has an
RQ, a fixed seed/target, a section and a time limit. `hdsc_schedule.py` regenerates
it byte-for-byte. Execution is core section followed by AI section, preserving
row order within each; global job IDs are identifiers, not an alternative order.
No GPU jobs overlap. A clean capability run precedes each sanitizer's reserved
runs. Randomization is fixed before outcomes are observed.

| RQ / purpose | Scheduled jobs | Workload requests | Detail |
|---|---:|---:|---|
| RQ2 tool capability | 3 | 3 | One healthy development input each: memcheck, initcheck, synccheck |
| RQ2 direct B0/B1/B3 | 240 | 240 | 10 blocks × 4 causes × 3 output profiles × healthy/injected; three verdicts from the same execution |
| RQ2 Compute Sanitizer B2 | 720 | 720 | The identical 240 workloads under each of the three tools |
| RQ3 native dynamic | 50 | 50 | 10 blocks × healthy plus L1/L2/C1/C2; 4–12 runtime-selected steps |
| RQ2/RQ3 trained Transformer faults | 40 | 80 | 10 blocks × 4 causes; randomized healthy/injected order within each pair |
| RQ2/RQ3 reserved healthy corpus | 80 | 80 | 10 distinct reserved seeds × 7 native patterns plus Transformer |
| RQ4 ON/OFF performance | 20 | 260 | 10 paired blocks × 2 modes; each mode has 3 warmup and 10 measured requests |
| **Total** | **1,153** | **1,433** | Includes 60 performance warmup requests and 200 measured requests |

There are **70 Transformer constructions**, each with nine eager setup forwards
and three graph-capture forwards: **630 eager + 210 capture forwards**, additional
to the 1,433 workload requests. These are setup operations, not independent
statistical runs. Each Transformer request generates 4–8 steps; tokens/forwards
are never treated as independent blocks. Model load/capture and image transfer
count toward the complete VM allocation interval, but not steady-state latency.

Racecheck: **0 launches**, documented UNSUPPORTED_CC. Random/B3/B4 search:
**0 runs**, deferred as secondary. Qwen: **0 new runs**; existing qualified assets
and results are preserved. RQ1 reruns: **0**.

If a sanitizer explicitly rejects this CC environment, keep its original
diagnostic; its 240 dependent jobs are recorded UNSUPPORTED/not executed.
Missing summaries, unexplained nonzero exits or timeout stop the window. A
nonactivation, missed detection or negative effect is retained as a scientific
outcome; it does not justify changing seeds or thresholds.

## Workload, baselines and reproducibility

- Four cause classes: L1 late dependency publication; L2 stale captured graph
  parameter; C1 stale generation; C2 wrong live compatible buffer.
- RQ2 profiles: changed final sum; equal payload with wrong identity/version;
  changed payload with identical modulo-2^32 sum. Inputs are identical across
  applicable baselines; activation is measured separately in each execution.
- Trained model: `roneneldan/TinyStories-1M`, revision
  `77f1b168e219585646439073245fe87e56b3023e`; seven assets, 51,943,120 bytes,
  plus a 1,107-byte manifest. Private Azure copy verified by full GET and SHA-256.
- PyTorch 2.8.0+cu128, Transformers 4.57.1; batch 1, FP32, TF32 off, eager
  attention, fixed 16-token context, no KV cache. ON/OFF share inputs, image,
  hardware, warmups and repetitions. Only ON snapshots and checks consumed state.
- Core: CUDA 12.8.1 build, sm90 plus compute90; bundled Compute Sanitizer
  2025.1.0.0. Installed help/version and actual capability results accompany
  the GPU evidence. No tool suppressions or CC development mode.
- Development seeds 82000–82007 (RQ2 uses two); reserved seeds 93000–93009;
  separate healthy reserved seeds 104000–104009. Versioned prompts are disjoint.
- Source hashes, generator, benchmark, schedule, model assets, protocols, image
  digests and CI are bound in the public qualification and executable plan.

## Duration and cost

**Maximum planned start-request-to-DEALLOCATED interval: 90 minutes.** This is
an operational deadline, not a measured completion-time forecast. The independent
Azure expiry requests deallocation at minute 87; the guest has an absolute
83-minute expiry and reserves its final two minutes before admitting another job.
The local controller also stops/collects/releases before the outer deadline.
No retry or next window is automatically authorized.

**Expected duration is not yet measured.** A planning scenario is 30–85 minutes
including startup, image/model preparation, execution and collection. It assumes
roughly 1–5 seconds per sanitizer process and modest model/capture startup time;
those assumptions are unverified on this CC host. Do not use them as a promise
that 1,153 jobs will fit. Record per-job wall time and the complete VM interval;
a deadline-censored campaign remains partial. Startup/pulls share the same clock.

Read-only Azure Retail Prices API query on 2026-10-10 selected exactly the Linux
`Virtual Machines NCCadsv5 Srs` consumption meter, East US 2,
`Standard_NCC40ads_H100_v5`: **6.98 USD/hour**. The Windows meter is excluded.
At 90 minutes: **10.47 USD compute**. Proposed maximum incremental window budget:
**12 USD**, allowing 1.53 USD for bounded evidence transfer/storage and margin.
Existing retained disk/IP recurring charges and tax are outside this incremental
window; no retail-price calculation is an exact invoice guarantee.
[Azure Retail Prices API](https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices),
[billed VM states](https://learn.microsoft.com/azure/virtual-machines/states-billing).

The timer begins with the start request, conservatively including initialization.
Only confirmed DEALLOCATED releases allocated compute; stopping the guest OS is
insufficient. Azure control-plane delays can exceed a requested deadline; keep
the independent guard armed and never report unconfirmed release as successful.

## Infrastructure, storage and stop policy

Use only retained VM `cc-contract-work-sample-1009b`, UUID
`2986ddd2-c122-4884-8f42-d7ad3d0a38ef`, and its existing 128-GiB OS disk, UUID
`323889df-fc1f-45ea-a54d-dd47ee8a1f52`. Create **0**, destroy **0** resources.
Keep driver 595.91.07, kernel 6.8.0-1066-azure-fde, CC ON/PRODUCTION and Secure
Boot. Do not alter MIG, GPU reset, system image or driver installation.

Reuse the existing managed-identity Logic App guard and verify its exact
read/deallocate-only role, target VM, definition and renewal readback. Do not
apply an old Terraform plan. Containers run serially, non-root, with no network,
read-only filesystems, bounded tmpfs/memory and only dedicated evidence/model
mounts. Model weights stay outside Git and images.

Storage allowance: 12 GiB free on the guest before starting; roughly 52 MB model,
existing/shared OCI layers, and at most 2 GiB uncompressed new scientific evidence.
No new managed disk. Private raw archives and full-GET verification use the existing
Azure artifact store. Only summaries/hashes go to GitHub. Local final image imports
share existing base layers; do not copy the AI image onto a second Kind worker or
prune unrelated Docker volumes.

On technical failure, stop the window and deallocate immediately. Partial
originals remain on the retained VM disk if collection cannot complete before
release; diagnose locally. Any later GPU recovery needs a fresh explicit plan
approval. On success, collect originals with transport hashes, deallocate, then
perform the independent CPU audit and private Azure backup. No GPU time is spent
writing the paper or computing bootstrap intervals.

## GO / NO-GO criteria and execution

Before approval: all local tests and relevant Kind checks pass; source CI is
green; no secret-scan finding; historical evidence unchanged; immutable images
published only after qualification; model/raw-development backups verified;
protocol and executable plan hashed; read-only inventory confirms DEALLOCATED.

After approval, before reserved work: exact VM/disk and image identities match,
expiry is armed and read back, original host configuration passes, model hashes
match, storage is adequate, and capability outcomes are preserved. Host errors,
CUDA errors, bad evidence or timeout mean stop/deallocate, not paid remote repair.

A runtime-verifier miss or a negative measured effect is not a protocol failure.
Do not modify the frozen detector after reading reserved outcomes. An ON/OFF
output mismatch invalidates that performance pair and stops for local diagnosis.
The report lists all incomplete/unsupported cases and uses independent blocks,
paired differences and 2,000-draw percentile 95% bootstrap intervals.

Commands (the second is **not authorized now**):

```sh
PYTHONPATH=src python3 scripts/hdsc-window.py review \
  --directory PRIVATE_NEW_WINDOW \
  --qualification results/manifests/hdsc-local-qualification.json

# Only after an actual fresh user approval of the exact plan SHA:
PYTHONPATH=src python3 scripts/hdsc-window.py run \
  --directory PRIVATE_NEW_WINDOW --approval PRIVATE_USER_RECEIPT \
  --model PRIVATE_VERIFIED_TINYSTORIES_DIRECTORY
```

The controller requires a receipt with approved_by=user, approved=true, the exact
plan SHA, protocol, 90-minute/12-USD limits, fresh UTC approval time and
reuse_completed_authorization=false. A locally generated receipt is valid only
when recording a real new user approval. Its exclusive execution-attempt file
prevents reuse. The current conversation authorizes preparation, not this window.

Offline analysis after release uses `scripts/analyze-hdsc-evaluation.py` on the
collected data directories and frozen plan/schedule. Exact archive SHA, per-file
hashes, raw statuses and missing-job counts remain part of the result provenance.
