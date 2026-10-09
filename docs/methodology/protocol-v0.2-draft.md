# Protocol v0.2 draft — bounded IR pilot and comparison preparation

This document extends the preserved v0.1 local protocol. It is **not frozen**
for confirmatory GPU comparison. Oracle and hardware qualification, a pilot
precision decision, and approval of the full costed schedule are prerequisites.

## Scope and independent sets

The original E1 development corpus remains 24 legal, 24 controlled mutants and
12 invalid cases. The extension has 96 separate generated legal cases: T01–T08
crossed with 12 sizes (1, 2, 31, 32, 33, 255, 256, 257, 4095, 4096, 4097,
65536 integers), seeds 1000–1095. T04 submits both buffers before observation;
T06 includes contiguous 2D shapes; T07 uses a mapped-host read kernel; T08
captures two copies and replays on fixed allocations with changing generations.
This is a bounded eight-template generator, not arbitrary CUDA program fuzzing.

All native copies include a separately allocated physical generation tag.
The Python reference defers operations, while the native CPU reference is
synchronous. Agreement tests the implementation on legal traces; neither
establishes CUDA legality, CC support, or GPU attestation. Capability probes are
real CUDA operations. Only explicit cudaErrorNotSupported is an unsupported
capability; other CUDA errors stop the run as infrastructure failures.
The pilot uses `--allow-unsupported` to continue after explicit unsupported
optional families. Their counts and incomplete qualification verdict remain
unchanged; they never become passing cases. Actual failures still block the
subsequent workloads.

Reserved evaluation schedules use independent block seeds >= 1,000,000 and
randomized within-block order. Parameter generation uses an independent PRNG
derived from each campaign seed. Development and historical cases must never be
presented as independent discoveries. H08/H09 are unreproduced reports: their
original version/model/input configurations and original evidence are missing.

## E1 and E7 numerical qualification

Integer values and physical tags use exact comparison. Linear float32 outputs
are checked against independently summed binary64 products of actual float32
inputs, using a conservative gamma(2n+2) forward-error bound. Nonfinite values
and violated normal-input assumptions are INCONCLUSIVE. A stable wrong value
does not increase the tolerance. TF32 is disabled.

The reduced-attention fixture uses bounded float32 inputs, a Decimal reference
at precision 60, and a conservative bound for dot/scaling, exponentials,
normalization and the final weighted sum. The assumed CUDA exp error bound must
be qualified for the actual kernel path. CUDA 12.8.1 documents expf at 2 ulp and
__expf at 2 + floor(abs(1.173*x)); this fixture keeps shifted scores near zero.
PyTorch contains both paths; GPU observations are still required before freeze.
Sources: [CUDA accuracy tables](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#mathematical-functions),
[PyTorch 2.8 softmax implementation](https://github.com/pytorch/pytorch/blob/v2.8.0/aten/src/ATen/native/cuda/SoftMax.cu).

Component qualification repeats token preparation, embeddings, linear operations
and reduced attention three times on synchronous and asynchronous transfer paths.
These repetitions are within one run. The local randomly initialized tiny
transformer is an API fixture, explicitly distinct from Qwen2.5-7B inference.

Qwen is revision a09a35458c702b33eeacc393d103063234e8bc28, loaded offline with
trust_remote_code=false. Freeze 24 synthetic prompts: eight each at exactly
32, 128 and 512 tokenizer tokens, plus an identical forced continuation. Record
full logits and last-layer hidden states. Pairing identical model arithmetic
tests transfer-path equivalence; it is not an independent proof of model
correctness. Differences are INCONCLUSIVE pending reproduction/localization.

## E4 and E5 policy definitions

Wall-clock budgets include generation, selection, validation, execution and
durable trace writing. CUDA context initialization is separate qualification.
All policies retain the final pre-execution safety validator.

| Policy | Stateful generations | Candidate selection |
|---|---|---|
| B1 | One generation, one replay | One independent random proposal |
| B2 | 2–8 generations where applicable | One random proposal |
| B3 | Same as B2 | 16 proposals, structural novelty |
| B4 | Same as B2 | Same pool size, structural + temporal novelty and diversity |
| A_NO_STATE | One generation, one replay | B4 selection |
| A_NO_DIVERSITY | B4 generation | B4 novelty, no repeat-signature penalty |
| A_NO_VALIDITY_GUIDANCE | B4 generation | B4 selection without preferring legal proposals |

Fifteen percent of proposals delete one sync; these are always rejected before
CUDA if invalid. Validity guidance changes proposal selection, not GPU safety.
B3 is the no-temporal-guidance ablation. B1 is not reused as no-state ablation:
it also changes the selection policy. Coverage is software feature coverage,
never a substitute for actual defect detection.

The initial schedule remains 20 paired independent blocks, seven policies,
600 seconds each: 140 campaigns / 23 h 20 min of campaign budget. E4 alone is
13 h 20 min. Counts may change only by a versioned pilot decision and user
approval. Fresh seeds are not selected after inspecting outcomes.

Primary outcomes are externally confirmed distinct defects per campaign and
probability of detecting any confirmed defect. FAIL alone is a candidate.
Confirmation requires two fresh failing replays under the same implementation
and explicit technical characterization; defect equivalence is reviewed using
the same characterized cause/mechanism, not family, token or observation count.
Nondetections remain right-censored at actual campaign end, never zero time.

Proposed useful-effect thresholds are +1 confirmed defect per campaign or
10 percentage points of detection probability. These are draft engineering
targets to justify with pilot precision and workload usefulness before freeze.
Use 95% paired block bootstrap intervals (5,000 resamples, seed 59001), Wilson
intervals for detection probability, exact paired McNemar tests, and Holm
correction for B4 versus B1–B3. No automatic superiority claim is emitted.
Incomplete budgets are reported and excluded from confirmatory comparisons;
CPU/GPU scopes, implementations, supported families and oracle versions cannot
be pooled. No repeated sampling until significance.

## E6 and E8 conditional evaluation

Both reducers validate each proposal before invoking the same anomaly-identity
predicate. Contract reduction additionally removes dependency consumers; ddmin
proposes plain deletions. Each accepted proposal requires three reproductions.
The bound is a wall-clock deadline; a native replay must also have a timeout no
longer than the remaining budget. Up to eight representative real traces, five
paired attempts, 60 s each. Controlled software predicates qualify algorithms
locally and never populate the real-anomaly results.

E8 requires a technically characterized anomaly and a correctness-qualified
intervention. Its ten paired blocks of 24 requests are not replaced with the
current diagnostic component timings. If no suitable case exists, record
CONDITIONAL_NOT_APPLICABLE and retain the negative detection evidence.

## Freeze prerequisites

Real native IR and float-component qualification, independent attestation review,
GPU pilot with compatible families, verified model cache and paired inference,
operational recreation and error/expiry release evidence, finalized practical
effect and precision plan, immutable images, budget approval and hashed protocol.
The current software preparation does not satisfy these hardware prerequisites.
