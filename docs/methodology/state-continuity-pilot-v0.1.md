# State continuity pilot v0.1

Status: local preparation only; no H100 run authorized. Fault provenance and
adaptations were specified [before implementation](state-continuity-fault-models-v0.1.md).

## Hypothesis and scope

An instrumented CUDA consumer can report a successful CUDA execution while
consuming a logical identity, generation or payload different from its trusted
host contract. CC-Contract compares `ObservedState(K)` with `ExpectedState(K)`.
Only an unequal pair with successful execution and a valid observation is a
`STATE_CONTINUITY_VIOLATION`. Other classes are `PASS`, `CUDA_ERROR`,
`INVALID_TEST`, `INFRA_FAILURE` and `UNSUPPORTED`. These are injected faults,
not discovered vulnerabilities or evidence of an NVIDIA defect.

The host creates immutable A/g1, A/g2 and B/g2 packets before injection. Each
packet is 19 uint32 words: identity, generation, length 16, then 16 payload
words. The expected contract is always A/g2. Payload words are SHAKE-256 of
`state-continuity-pilot-v0.1/<seed>/<identity>/<generation>`, decoded little
endian. A SHA-256 over the 64 payload bytes is the reported payload tag.
This packet generator does not decide a detection result.

The CPU adapter maintains byte-addressed snapshots and explicit dependency
operations. The CUDA adapter changes transfer timing, graph kernel parameters
or valid pointers. Neither adapter computes the contract verdict. The consumer
reads one packet, computes a uint32 sum and emits the same loaded packet.
The separate oracle checks the computation and exact payload, identity and
generation. It takes only the trusted expected contract and observation;
neither a fault flag nor the scenario name is an oracle input. Unit controls
change injection labels independently, neutralize injections, forge header
metadata while retaining stale payload, and shuffle unlabeled observations.

Instrumentation is trusted. This is not cryptographic proof against an attacker
who can forge all observations, a monitor for arbitrary uninstrumented kernels,
or evidence of isolation/attestation security. Producer/stream/event/consumer
labels describe the host contract; the device independently reports only the
consumed identity, generation and payload.

## Frozen bounded matrix

Ten blocks with seeds 71000–71009. Every block has L1, L2, C1, C2 injected and
one healthy run. The healthy variant cycles L1, L2, C1, C2 (3, 3, 2, 2 runs).
Within-block order uses Python `random.Random(10102026).shuffle`; the exported
schedule and its SHA-256 are the authoritative replay input. All 50 runs are
serial, each in a fresh CUDA worker process, one consumer kernel per run.
Additional per-fault healthy controls are CPU unit tests, not extra H100 runs.
No warm-up campaign, random search, B3/B4 comparison, retry or automatic extension.

L1's forced consumer-before-late-producer schedule is race-free and explicitly
an adaptation. L2 keeps the old and new allocations alive and immutable;
changing a host pointer variable alone does not update a captured graph.
C1 omits the second transfer; C2 substitutes the compatible B allocation.
These models and the scheduling intervention must not change in response to
GPU results without a new protocol version.

## Metrics and failure handling

Report every scheduled run, including errors, unactivated faults and missing
runs. Activated means the observed identity/generation is the declared wrong
state after a successful execution; merely requesting a fault is insufficient.
Detected means an activated fault received `STATE_CONTINUITY_VIOLATION`.
Missed means activated but not detected. Report unactivated injections separately.
Healthy alerts are false positives. Preserve expected/observed payload tags,
raw consumed words, the sum, host timing and all original worker responses.

Host detection time uses `perf_counter_ns` immediately around classification.
The detector's added host processing cost is reported in ns and as a fraction
of worker wall time. That fraction is **not total GPU instrumentation overhead**:
packet tagging, output traffic and synchronization overhead require a separate
matched uninstrumented workload. This pilot records that quantity as unmeasured,
rather than inventing a causal performance comparison within these 50 runs.
CPU-model timings must never predict H100 kernel latency.

Record source commit, OCI digest, protocol/schedule/source hashes, seeds, driver,
Linux kernel, CC mode, Secure Boot, original evidence hashes and UTC lifecycle.
Only the CUDA worker may report `CUDA_SUCCESS`; CPU reports `MODEL_SUCCESS`.
The first CUDA, malformed-output, timeout or infrastructure error stops the
remaining pilot; preserve partial evidence and deallocate before diagnosing.
Nondetection/healthy alerts remain scientific results; do not tune or rerun.

## Predeclared decision

Technical gate: exactly 50 valid CUDA-successful observations, known host state,
verified originals, no healthy alerts, no injected-fault misses, and at least
two distinct fault models with at least one observed activation and detection.
Report all four fault models separately even if only two activate. Repeated
deterministic scenarios establish mechanism feasibility, not population power,
independent field-defect samples, B4 superiority or a low false-positive rate.
Even 0/10 healthy alerts gives a one-sided exact 95% upper bound of about 25.9%
under an IID Bernoulli assumption; those assumptions are not established here.

NO-GO for a fault if only CUDA errors occur, the wrong consumed state cannot be
observed, detection requires the injected label, or its execution scenario is
implausible. NO-GO for expansion if healthy alerts or invalid evidence occur.
The completed 140-job integer baseline stays unchanged in its own namespace;
this pilot neither replaces it nor reclassifies its 2,377 rejected cases as
successful CUDA executions.

## Reproduction

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_continuity_pilot.py
PYTHONPATH=src python3 -m cc_contract.continuity_pilot --output /tmp/continuity-cpu-new
docker build -f infrastructure/state-continuity/Dockerfile \
  --build-arg CC_COMMIT="$(git rev-parse HEAD)" -t cc-contract-continuity:local .
python3 scripts/qualify-continuity-kind.py --image cc-contract-continuity:local \
  --output /tmp/continuity-kind-new
```

Output directories must be new: reruns cannot overwrite original evidence.
The separate costed window and fresh user approval are mandatory for any H100
use; none of the local reproduction commands starts cloud compute.
