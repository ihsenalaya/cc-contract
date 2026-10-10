# Runtime Semantic State-Continuity Verification for Confidential GPU Execution

Research manuscript draft, 11 October 2026. This document consolidates the
implemented method and audited evidence; it is not a submitted or accepted paper.
Author information, venue formatting and independent scientific review remain
editorial steps. The [completion register](completion-register.md) separates
finished artifacts from unavailable comparisons and unestablished claims.

## Abstract

A successful CUDA computation can consume a live, initialized buffer that differs
from the logical object or version intended by its application. We study this
application-level mismatch under confidential GPU execution. CC-Contract
represents expected and consumed state through the Host–Device State Continuity
model (HDSC) and checks relations incrementally at instrumented consumer
boundaries. The verifier uses trusted application intent and runtime witnesses;
it does not require the application's complete future execution trace. On a
confidential H100, a controlled benchmark detects 120 of 120 injected semantic
violations, including 80 cases whose final integer output agrees with an exact
output oracle. Separate dynamic native and pretrained Transformer evaluations
each detect 40 of 40 injections. An additional healthy corpus produces no alerts
in 80 runs. Ten paired Transformer performance blocks show a mean increase in
block-median latency of 0.567 ms, with a 95% block-bootstrap interval of
[0.467, 0.680] ms. Compute Sanitizer rejects the tested confidential configuration,
so its detection comparison is unavailable. These results establish a bounded
implementation and measurement result, not general detection superiority,
adversarial integrity or novelty over all prior runtime monitors.

## 1. Problem and research questions

Suppose two allocated token buffers have the same shape and remain valid. An
application intends to consume the latest version in one buffer but replays a
graph bound to the other. API completion status does not encode that intent.
Likewise, an output oracle cannot distinguish different consumed states if they
produce the same output. Whether such a difference matters depends on the
application's identity and version contract.

We investigate four questions. RQ1 asks whether CUDA-successful unintended-state
consumption can be observed and detected. RQ2 asks what detection value state
verification adds to CUDA status, exact output validation and applicable
Compute Sanitizer tools. RQ3 asks whether the verifier works as host control flow
and execution length depend on preceding outputs. RQ4 measures application
overhead with the monitor disabled and enabled under otherwise paired conditions.

The contribution is limited to three parts: **C1**, an executable relational
state model; **C2**, a trusted online verifier and instrumented consumers;
and **C3**, a bounded confidential-H100 evaluation with explicit exclusions.
The proposed scientific distinction is the application's incremental declaration
and checking of logical state. Establishing priority or broad superiority is a
separate claim that this evaluation does not settle.

## 2. Context and related work

LGT4CG validates prepared execution metadata and checks kernel pointer relations;
this directly overlaps state-consistency concerns. We have not established that
its dynamic capabilities exclude our workloads. Its different trust boundary
precludes a security-superiority claim from our results.
[LGT4CG, §4.2](https://doi.org/10.1016/j.sysarc.2026.103886).

Blueprint, Bootstrap, and Bridge examines NVIDIA confidential-GPU architecture,
startup and protected transfers. We address application intent inside a trusted
stack, without claiming a new confidentiality failure.
[MLSys 2026 paper](https://proceedings.mlsys.org/paper_files/paper/2026/hash/906419cd502575b617cc489a1a696a67-Abstract-Conference.html).

Simulee models memory accesses to investigate CUDA synchronization bugs; MUTGPU
uses mutation testing for GPU programs; cuFuzz explores CUDA applications through
coverage-guided fuzzing. Their objectives motivate complementary testing rather
than demonstrate an HDSC baseline result. We execute none of these systems in
this study.
[Simulee](https://lingming.cs.illinois.edu/publications/icse2020b.pdf),
[MUTGPU](https://pure.tudelft.nl/ws/portalfiles/portal/124438843/09159103.pdf),
[cuFuzz author artifact](https://github.com/NVlabs/cuFuzz).

Compute Sanitizer supplies runtime CUDA correctness checks; the PTX memory-model
literature concerns ordering semantics. Neither the description of those scopes
nor an unavailable tool execution establishes a measured detection disadvantage.
[Compute Sanitizer](https://docs.nvidia.com/compute-sanitizer/ComputeSanitizer/index.html),
[PTX memory-model analysis](https://research.nvidia.com/publication/2019-04_formal-analysis-nvidia-ptx-memory-consistency-model).
The [comparison matrix](related-work-matrix.md) records narrower source-backed
claims and unresolved fields. We do not compare percentages from unrelated papers
as if they were measurements on our hardware and workload.

## 3. HDSC and implementation

For a consumer K, define

```text
S(K) = (buffer_id, generation, producer, stream,
        dependency, consumer, payload_tag)
```

The application declares an expected state before an injection or consumer
launch. The adapter constructs an observed state from the selected allocation,
executed relations and bytes actually consumed. A generation increases for a
logical buffer; an event epoch binds an allocation and its version; a graph
instance binds its captured allocation. A host variable changing to another
allocation does not by itself change that recorded binding.

The ledger records declarations, transfers, event recording, waits, captures,
launches and completions as they occur. It refuses overwriting a pending consumer
allocation and reusing a logical buffer with an unretired consumer. On completion,
it checks the expected and observed fields and whether the required dependency
binds the consumed allocation and state. No seed, injection label or list of
future operations is passed to the verifier.

For valid evidence with CUDA success, agreement produces PASS; disagreement
produces STATE_CONTINUITY_VIOLATION. CUDA_ERROR, INVALID_TEST, INFRA_FAILURE and
UNSUPPORTED remain distinct outcomes. CPU model success never counts as CUDA
evidence. The [model](hdsc-model.md) and
[runtime source](../../src/cc_contract/hdsc_runtime.py) specify these rules.

The native consumer exposes consumed identity, generation and payload, together
with its sum/xor consumer discriminator. Producer, stream and event attribution
come from the trusted API adapter. The Transformer consumes the exact input
snapshot returned to the verifier; its consumer name is also adapter-supplied.
Consequently, the complete seven-field state is not independently device-attested.
RQ2 specifically evaluates the buffer/generation/payload projection; the dynamic
workload exercises the wider online relation checker.

## 4. Trust and fault model

We trust the intent constructor, verifier, instrumented consumer and API adapter
inside the qualified stack. A compromised trusted component can forge a
self-consistent witness. The verifier cannot infer that the application's own
declared intent is wrong. We make no claim about arbitrary uninstrumented
kernels, memory-safety proofs, side channels or replacement of attestation.
CC ON / PRODUCTION and Secure Boot describe the tested environment; they do not
establish a new independently verified GPU quote. See the
[threat model](threat-model.md).

Four controlled causes are implemented: L1 delays publication of intended state
until after consumption; L2 reuses an old captured graph binding; C1 consumes a
stale generation; and C2 selects a wrong compatible live buffer. They avoid
deliberately introducing invalid lifetimes or undefined data races. These
application-boundary injections are not discovered CUDA or NVIDIA defects.

## 5. Evaluation method

### Workloads, counts and separation

The historical RQ1 pilot remains immutable: 50 runs, with 40 detected injected
violations and ten healthy runs without alerts. Its observations are not pooled
with this evaluation or the earlier 140-job campaign.

The new schedule accounts for 1,153 records. Of these, 433 jobs executed:
three tool capability controls, 240 direct RQ2 runs, 50 native dynamic runs,
70 additional native healthy runs and 70 AI jobs. Another 720 tool-dependent
records are explicit unsupported skips, not executions. Two additional GPU
development equivalence controls preceded the final AI jobs.

RQ2 crosses four causes, three state/output profiles and healthy/injected pairs
in ten blocks. The profiles change the final output, preserve the payload while
changing identity/version, or change payload while preserving the modulo-2^32
sum. Thus 120 injected cases are parameter variants, not 120 distinct defects.
CUDA status (B0), exact output validation (B1) and CC-Contract (B3) read the same
direct execution. B2 was to execute instrumented copies, subject to capability
qualification. Its three controls rejected the tested CC environment, so no B2
detection-rate denominator is constructed.

The native dynamic workload reuses three packets and two streams, uses events,
and chooses buffer, consumer and graph/direct dispatch from prior outputs. It
runs 4–12 steps. Ten blocks pair a healthy run with each of four injections.
The separately seeded healthy corpus contains eight patterns per block, including
the Transformer, for 80 runs. This checks realized paths without giving the
verifier a complete anticipated trace. It does not demonstrate arbitrary dynamic
control flow inside a captured CUDA graph.

The real AI workload uses pretrained TinyStories-1M, revision
`77f1b168e219585646439073245fe87e56b3023e`, PyTorch 2.8.0+cu128 and Transformers
4.57.1. It uses batch 1, FP32, 16-token persistent inputs, no KV cache and 4–8
generated tokens. Four fault pairs in each of ten blocks give 80 requests;
ten additional healthy jobs complete the separate healthy corpus. The 20
performance jobs form ten randomized ON/OFF block pairs, with three warmups
and ten measured requests per mode: 60 warmup and 200 measured requests.

### Comparability and failure handling

Both performance modes retain hardware CC ON and share the same immutable image,
weights, inputs, seeds and software stack. ON adds input-state snapshots, witness
transfers and verification. Timing includes application harness work. Setup and
graph capture are excluded from steady-state latency but included in VM time.
Token disagreement invalidates a performance pair; none occurred.

An initial interrupted attempt is excluded in full. Some reserved inputs were
exposed, so this corpus is not described as an untouched holdout. The subsequent
native section completed, but first-model AI construction failed during CUDA
Graph capture. Its AI section contributes zero completed jobs. A correction
preallocated the same scalar attention-mask constant before capture, retaining
attention arithmetic and weights in both ON/OFF modes. Original eager, adapted
eager and captured replay logits then matched exactly on three buffers in each
of two GPU development controls before the 70 AI jobs were admitted. No seeds,
thresholds or fault profiles were replaced after observing results.

Native and AI evidence have separate source/image identities. The offline audit
checks frozen schedule membership, archive/file hashes, native arithmetic,
consumed-state verdicts, model argmax outputs and development equivalence vectors.
It runs after deallocation and does not invoke the injector or detector to
reproduce their verdicts. This independent recomputation is not an independent
laboratory replication or proof that a malicious measurement stack cannot lie.

### Statistical unit

The unit is a block, not a token, packet or individual repeat. Paired absolute
differences use a deterministic 2,000-resample percentile bootstrap over ten
blocks. Relative change is undefined for a zero baseline. We distinguish the
average of per-block relative changes from the relative change of block means.
The intervals are descriptive for this small constructed corpus; they do not
establish deployment prevalence or universal sensitivity. This enumerated
benchmark does not support search-efficiency or time-to-discovery claims.

## 6. Results

| Evaluation | Injected detection | Healthy alerts | Scope |
|---|---:|---:|---|
| Historical RQ1 | 40/40 | 0/10 | Separate feasibility pilot |
| RQ2 direct | 120/120 | 0/120 | Four causes, three profiles, ten blocks |
| RQ3 native | 40/40 | 0/10 | Online dynamic streams |
| AI paired faults | 40/40 | 0/40 | Four causes, ten blocks |
| Additional healthy corpus | Not applicable | 0/80 | 70 native + 10 AI |

All 120 RQ2 injected executions completed with CUDA success. Exact output
validation detected the 40 changed-output cases and missed the 80 equal-output
cases; CUDA status did not detect these semantic violations. The paired detection
difference against B1 is zero for the changed-output profile and +100 percentage
points for each equal-output profile. Corresponding intervals are [0, 0] and
[100, 100] points. Those degenerate intervals reflect consistent outcomes of
constructed cases, not certainty about unseen software faults. B1's successful
changed-output detection is retained as a positive baseline result. The
Compute Sanitizer comparison remains unanswered.

Each AI cause was detected in all ten injected requests; all 40 injected token
sequences differ from their healthy partners. The step-2 logit L-infinity
differences range from 11.5305 to 24.9949. These changes establish output impact
in this workload, not a general model-quality loss. Zero alerts in the separate
healthy corpus cannot establish a zero population false-positive rate.

All ten performance pairs retained equal token outputs. The following figures
are means of block metrics, rather than pooled latency percentiles. Intervals
refer to paired absolute differences. The relative column averages block ratios.

| Metric | OFF | ON | Difference [95% CI] | Relative change |
|---|---:|---:|---:|---:|
| Latency p50, ms | 26.9630 | 27.5302 | +0.5671 [0.4668, 0.6803] | +2.16% |
| Latency p95, ms | 27.1127 | 27.6487 | +0.5360 [0.4892, 0.5930] | +2.14% |
| Requests/s | 40.3438 | 39.4732 | −0.8706 [−1.0851, −0.6771] | −2.10% |
| Tokens/s | 207.0662 | 202.5594 | −4.5068 [−5.7208, −3.4710] | −2.10% |
| First-token p50, ms | 1.9592 | 2.0120 | +0.0528 [0.0467, 0.0601] | +6.29% |
| CPU verifier p50, ms | 0 | 0.2548 | +0.2548 [0.2150, 0.3028] | Undefined |

The relative change of mean p50 latency is +2.10%, distinct from the +2.16%
average of block ratios. GPU stream interval p50 increases by 0.5679 ms
[0.4687, 0.6809]; it includes waits and host gaps rather than isolated SM-active
time. CPU verifier time covers relation checks, not every instrumentation cost.
Persistent input storage rises from 384 to 456 bytes. ON averages 10.8 additional
copies and 5.4 witness synchronizations per request. The peak allocated-memory
effect is negative, −6,708,377.6 bytes, with interval [−16,774,656, 2,508.8]; we
retain it but infer no memory saving or isolated monitor-memory reduction because
the interval spans zero and the statistic includes process allocation history.

The [complete results](../environment/hdsc-final-evaluation-result.md) and
[derived analysis](../../results/manifests/hdsc-final-evaluation-analysis.json)
provide all block values and secondary metrics. The last AI window lasted
422.484124 seconds from start request through collection to confirmed
deallocation. Across the interrupted, native, recovery-only and final AI windows,
the corresponding total was 1,673.427687 seconds. These are wall-clock intervals,
not a statement of invoiced cost.

## 7. Interpretation and threats to validity

The result supports a narrow proposition: observing consumed state adds detection
information when the application's required identity/version is not determined
by its final output. It does not show that state verification improves every
application, or that output validation should be removed. The state predicate
and trust assumptions must be justified for each consumer.

Faults are engineered; real-world frequency and naturally occurring defects were
not studied. The GPU host, small model, fixed input width and short outputs limit
external validity. There is no independent-host replication, production Qwen
overhead estimate or parallel-job study. The native projection and richer dynamic
monitor must not be presented as identical device-observation capabilities.

Input exposure and the corrective restart limit claims of a pristine evaluation
split. Exact equivalence gates support arithmetic preservation but do not prove
universal equivalence for all prompts, dtypes or library versions. The absence
of B2 measurements leaves that part of RQ2 unresolved. A different tool/host
configuration would require a separate justified protocol and approval, rather
than silently changing CC mode. The prior-art distinction also remains provisional;
our implementation result alone does not establish a Q1-level novelty claim.

## 8. Reproducibility and data availability

The [provenance manifest](../../results/manifests/hdsc-final-evaluation-result.json)
binds each section to its exact source, image, plan and original archive hashes.
Public files include schedules, parameterized targets, analysis code, derived
block metrics and [incident history](../incidents/incidents.jsonl). Original
traces and complete logits remain in private Azure storage, with full remote
byte/SHA-256 verification. Public summaries alone cannot independently validate
those private originals; a reviewer requires authorized access. No public raw-data
release or independent reproduction is claimed.

The [offline review guide](../reproducibility/hdsc-offline-audit.md) describes
recomputation using authorized originals and public-summary checks without CUDA.
The old RQ1 and 140-job evidence remains unmodified. H100 resources are retained
and deallocated; commands in the repository do not authorize a restart.

## 9. Conclusion

CC-Contract implements a trusted online state-continuity check and demonstrates
its operation on bounded native and pretrained-model workloads on a confidential
H100. It detects deliberately induced state mismatches that CUDA status and, for
equal-output cases, an exact output oracle do not expose. The measured latency
cost is small in this workload, with the reported uncertainty and instrumentation
scope. Unavailable sanitizer comparisons, trusted observations and provisional
novelty remain explicit limits of the contribution.
