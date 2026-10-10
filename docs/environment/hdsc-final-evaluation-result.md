# HDSC v1 — completed supported H100 evaluation

The supported frozen matrix is complete and independently audited: **433 executed jobs**, plus **two additional GPU development controls**. The schedule contains 1,153 records because **720 Compute Sanitizer jobs were explicitly unsupported and never executed**. Their comparison remains unavailable. There are no missing schedule records and no invalid ON/OFF pairs.

The final AI window completed 70/70 sequential jobs after local qualification and exact GPU equivalence gates. Start request: `2026-10-10T20:56:28.019552+00:00`; confirmed deallocation: `2026-10-10T21:03:30.503676+00:00`. **Total H100 window: 422.484124 seconds (7 min 02 s)**, including startup, collection and release. VM and disk are retained; seven ARM resources remain, with zero deletions. No further start is authorized by this completed window.

## Detection and dynamic execution

| Evaluation | Actual observations | Audited result |
|---|---|---|
| RQ2 direct | 120 injected + 120 healthy | 120 injected detections; 0 healthy alerts; CUDA success |
| Output-only baseline | Same direct runs | Detects 40 changed-output cases; misses 80 equal-output cases |
| CUDA-status baseline | Same direct runs | Misses all 120 semantic violations |
| RQ3 native dynamic | 40 injected + 10 healthy | 40 injected detections; 0 healthy alerts |
| AI fault pairs | 40 injected + 40 healthy requests | 40 detections; 0 healthy alerts; all 40 token sequences change |
| Separate healthy corpus | 70 native + 10 Transformer | 0/80 runs with alerts |
| Compute Sanitizer | 3 capability controls | memcheck/initcheck/synccheck disabled by tested CC environment |

RQ2 paired detection difference against CUDA status is +100 percentage points in each profile. Against exact output validation it is 0 for changed outputs and +100 points for both equal-output profiles. The ten-block percentile bootstrap intervals are respectively [100, 100] and [0, 0] points. These degenerate intervals describe this constructed corpus, not universal sensitivity. Relative effects against a zero detection denominator are undefined. Native RQ3 healthy-to-injected difference is +100 points, interval [100, 100]. No unsupported-tool detection denominator is created.

Each AI class (L1, L2, C1, C2) has 10/10 injected detections and 0/10 paired healthy alerts. The observed step-2 logit L-infinity differences range from 11.5305 to 24.9949. These are deliberately injected application-boundary faults, not newly discovered defects. Zero healthy alerts in this limited corpus does not establish a zero population false-positive rate.

## Application overhead

Real pretrained TinyStories-1M, pinned revision `77f1b168e219585646439073245fe87e56b3023e`, FP32, batch 1, 16-token input, no KV cache, 4–8 generated tokens. Hardware CC remains ON in both modes. Ten paired blocks contain 60 warmup and 200 measured requests; all paired token outputs match. Values below are means of block-level metrics, not pooled percentiles. CI is the predeclared 2,000-resample paired-block bootstrap of the absolute difference.

| Metric | OFF | ON | ON − OFF [95% CI] | Mean per-block change |
|---|---:|---:|---:|---:|
| Latency p50 (ms) | 26.9630 | 27.5302 | +0.5671 [0.4668, 0.6803] | +2.16% |
| Latency p95 (ms) | 27.1127 | 27.6487 | +0.5360 [0.4892, 0.5930] | +2.14% |
| Requests/s | 40.3438 | 39.4732 | -0.8706 [-1.0851, -0.6771] | -2.10% |
| Tokens/s | 207.0662 | 202.5594 | -4.5068 [-5.7208, -3.4710] | -2.10% |
| First-token p50 (ms) | 1.9592 | 2.0120 | +0.0528 [0.0467, 0.0601] | +6.29% |
| GPU stream interval p50 (ms) | 26.9083 | 27.4762 | +0.5679 [0.4687, 0.6809] | +2.16% |
| CPU verifier p50 (ms) | 0.0000 | 0.2548 | +0.2548 [0.2150, 0.3028] | undefined |
| Peak allocated GPU bytes | 604555417.6000 | 597847040.0000 | -6708377.6000 [-16774656.0000, 2508.8000] | -1.47% |
| Persistent input bytes | 384.0000 | 456.0000 | +72.0000 [72.0000, 72.0000] | +18.75% |
| Extra copies/request | 0.0000 | 10.8000 | +10.8000 [9.2000, 12.8000] | undefined |
| Witness synchronizations/request | 0.0000 | 5.4000 | +5.4000 [4.6000, 6.4000] | undefined |

The latency p50 effect is +0.5671 ms: +2.16% averaged over per-block ratios, or +2.10% as the ratio of block means. Both estimands and every block are published; they are not interchangeable. Timing includes this bounded harness and its output handling, and is not a production-serving throughput estimate. GPU event intervals include waits and host gaps, not just SM-active execution.

The negative peak-memory estimate is retained: its interval includes zero, and process/allocator history varies across blocks. It is not evidence that instrumentation saves memory. The directly counted persistent-input increase is 72 bytes. CPU verifier time excludes other instrumentation work; the full ON/OFF latency includes it. No thresholds, seeds or workloads were changed to improve these results.

## Capture correction and provenance

The earlier first-model failure came from constructing a scalar mask tensor during CUDA Graph capture in pinned Transformers 4.57.1. The correction allocates that same constant before capture and preserves the original attention arithmetic, weights and both modes. It does not substitute a different attention algorithm or fall back from CUDA Graphs. Before reserved work, original eager, adapted eager and captured replay logits matched exactly on three live buffers in each of two GPU development controls; healthy ON/OFF tokens also matched. The independent offline audit rechecked the complete stored vectors.

The native section comes exclusively from `hdsc-eval-1010b`; the AI section exclusively from `hdsc-ai-1010d`. Their different source commits, immutable images, plans and archive hashes are explicit in the [result manifest](../../results/manifests/hdsc-final-evaluation-result.json). The [complete derived analysis](../../results/manifests/hdsc-final-evaluation-analysis.json) contains per-block metrics and counts. Complete original outputs remain private on Azure, verified by full remote download and SHA-256. Analysis ran after deallocation; a subsequent read-only inventory independently confirmed retained VM/disk identity and deallocation.

The first interrupted window `1010a` is excluded as a whole. Its previously exposed inputs are disclosed and cannot be described as an untouched holdout. The failed AI start in `1010b` contributes zero AI jobs. RQ1 and the older 140-job campaign are preserved separately and never pooled.

## H100 time and limits

| Window | Purpose | Start-to-confirmed-release |
|---|---|---:|
| 1010a | Interrupted attempt, excluded | 289.713887 s |
| 1010b | Native results; AI construction failed | 791.671670 s |
| 1010c | Recover original logs, zero experiments | 169.558006 s |
| 1010d | Two GPU controls + 70 AI jobs | 422.484124 s |
| Total of these four windows | Includes failures and recovery | 1,673.427687 s (27 min 53 s) |

These are conservative wall-clock windows, not an Azure invoice. The latest AI section itself lasted 120.523633 s; startup, evidence transfer and release account for the rest. Setup outside request latency comprises 864 warmup/capture forwards across 72 model instances plus 18 equivalence forwards. The window contains 352 requests, including two development controls. No GPU job ran in parallel.

Recorded job timers below include each model construction and its requests;
they exclude inter-job cleanup, summary serialization and the two development
controls. Their sum therefore differs from the full section and VM intervals.

| AI job type | Jobs | Total job time | Median/job | Range/job |
|---|---:|---:|---:|---:|
| Healthy/injected pair | 40 | 42.697 s | 1.041 s | 0.956–1.320 s |
| Additional healthy | 10 | 6.017 s | 0.602 s | 0.584–0.616 s |
| Performance mode | 20 | 18.773 s | 0.868 s | 0.778–1.356 s |

The supported bounded matrix is complete. B2 remains unavailable on this tested CC host, rather than passed or defeated. Novelty relative to LGT4CG remains provisional; seven-field verification relies partly on a trusted host adapter, and RQ2 exercises its buffer/generation/payload projection. No production-model, independent-host replication, general security superiority or Q1 acceptance claim follows. See [limitations](../paper/limitations.md).
