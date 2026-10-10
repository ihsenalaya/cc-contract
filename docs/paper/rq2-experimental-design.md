# RQ2 — detection value, v1

Use `experiments/hdsc-fault-benchmark-v1.json`. Four cause classes have three
predeclared state/output variants: changed final sum, equal payload with changed
identity/version, and different payload with the same modulo-2^32 sum. These are
four causes and twelve state profiles, not 120 newly discovered defects. Ten
reserved blocks vary payloads, IDs and generation gaps; two development blocks
are disjoint. The balanced construction is a stress corpus, not a prevalence model.

On each identical target/healthy pair: B0 reads only actual CUDA status; B1 compares
only the complete final integer sum with its independent exact reference; B3 uses
the qualified consumed-state detector. This reused worker verifies the
buffer/generation/payload projection; producer/stream/dependency/consumer remain
protocol context in RQ2. The seven-field online relation checker is exercised
separately by RQ3, with its documented host-adapter trust boundary. All three read one direct execution. B2 separately
runs exactly the same binary, input bytes, seed and injection under memcheck,
initcheck and synccheck. Tool instrumentation can change execution; compare actual
activation across tool/direct pairs, do not silently transfer activation labels.

Racecheck is recorded UNSUPPORTED_CC, with zero planned launches. NVIDIA lists
this limitation; it cannot count as a missed detection. The other three tools
need a clean healthy capability run inside the approved window. A tool launch
failure, absent completion summary or timeout is not a clean report. Retain raw
stdout/stderr, return code, tool version and observation. No suppressions, forced
blocking launch or disabling binary patching is permitted.
[NVIDIA Compute Sanitizer](https://docs.nvidia.com/compute-sanitizer/ComputeSanitizer/index.html),
[release limitations](https://docs.nvidia.com/compute-sanitizer/ReleaseNotes/index.html).

Reserved matrix: 10 blocks × 4 faults × 3 profiles × healthy/injected ×
(direct + 3 tools) = **960 scheduled process runs**. Direct execution has 240 runs,
720 tool runs. Development CPU qualification exercises 48 direct model runs;
no simulated sanitizer verdict or simulated CUDA_SUCCESS is reported.

Primary effect: paired block-level difference in detected activated violations
between CC and each applicable baseline, stratified by output profile. Report
activation, raw counts, absolute differences, relative differences when defined,
and deterministic 2,000-resample percentile 95% block bootstrap intervals. Ten
blocks yield coarse uncertainty; the design supports a bounded benchmark claim,
not a powered universal advantage claim. Never bootstrap packets as independent.
Preserve misses, alerts and nonactivations. Unsupported tools have no detection-rate
denominator. Candidate-budget/first-detection metrics apply only if search is later
retained; they do not turn this enumerated fault test into a discovery campaign.
