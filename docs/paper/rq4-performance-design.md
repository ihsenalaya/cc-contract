# RQ4 — application overhead protocol

Use the trained `roneneldan/TinyStories-1M` checkpoint at revision
`77f1b168e219585646439073245fe87e56b3023e`, PyTorch 2.8 / Transformers 4.57.1,
16-token persistent input buffers, batch 1, FP32, eager attention, TF32 disabled.
It is a real pretrained language model, not the prior random tiny-model fixture.
The workload generates 4–8 tokens, reuses buffers, versions inputs and chooses
host-side graph/eager dispatch from runtime token values. It has no KV cache;
results cannot represent Qwen7B, long-context serving or production throughput.
[Checkpoint and model card](https://huggingface.co/roneneldan/TinyStories-1M).

Instrument the boundary actually consumed by the model. ON clones a tagged input
snapshot, passes its token view to the Transformer and verifies the same consumed
snapshot. OFF omits state headers, snapshot, witness transfer and verifier. All
other inputs, weights, image, hardware, paths and output processing match. There
is no artificial sleep and no sanitizer during performance runs. Weights remain
outside the image, hash-verified and mounted read-only; the existing Qwen assets
are retained, but Qwen execution is deferred to avoid unsupported extrapolation.

Ten paired blocks with ten distinct reserved prompts, disjoint from development
and reserved healthy prompts (`experiments/hdsc-AI-inputs-v1.json`); within-block
ON/OFF order randomized deterministically. For
each mode: three warmup requests, ten measured requests, fresh model instance.
Construction also performs exactly nine eager warmup forwards and three graph
capture forwards per CUDA model instance (three persistent slots). These are
explicit setup work, excluded from steady-state latency and included in VM time.
260 requests = 60 warmup + 200 measured; 20 constructions add 240 setup forwards.
No statistical inference treats those forwards/tokens as independent blocks.

Report latency p50/p95, requests/s, generated tokens/s, TTFT, GPU stream event
interval, CPU verdict/relation-check time, persistent input bytes, peak allocated GPU memory,
extra copies and witness synchronization points. CUDA events include waits and
host launch gaps; they are not isolated SM-active time. Do not enable CUPTI or
CC development mode. CPU smoke timing only verifies the metric pipeline.

For each block/metric, overhead = (ON − OFF)/OFF × 100; zero denominator is
undefined. Report paired absolute effects and 95% block bootstrap uncertainty.
Retain negative overheads and output/path disagreements; a disagreement makes a
performance pair invalid, not a speedup. ON/OFF compares the application monitor,
with hardware CC remaining ON in both variants. The pilot's roughly 40 µs host
comparison is not total overhead. Model load/capture/cold-start are reported
separately from steady-state timing.

AI fault evaluation: 10 blocks × 4 fault classes × healthy/injected = 80 requests.
Record the complete observed input, expected state, actual CUDA status, detection,
logit changes and generated-token changes. L1 delays publishing the intended
persistent slot until after consumption; C1 omits that publication; C2 selects a
live compatible slot; L2 replays the graph with its old captured input address.
These are controlled application-boundary faults, not defects in trained weights.
