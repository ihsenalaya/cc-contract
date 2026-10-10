# State-continuity fault models v0.1

Namespace: `state-continuity-pilot-v0.1`. Prepared before implementation on
2026-10-10. This is an injected-fault mechanism pilot, not vulnerability discovery,
not a B3/B4 comparison, and not evidence that confidential computing is broken.

| ID | Source | Type | Description source | Adaptation CC-Contract | Identique/adaptée/nouvelle |
|---|---|---|---|---|---|
| L1 | Zhu & Zaidman, MUTGPU [1], §IV-B synchronization, Listing 14; Simulee [2], §3.2 motivates access/dependency modeling only | LITERATURE_DERIVED | MUTGPU removes a synchronization call inside a kernel | Replace the required generation-2 event dependency with the generation-1 dependency; force a consumer-before-producer schedule without concurrent conflicting accesses | ADAPTED_FROM_PUBLISHED_SYNCHRONIZATION_FAULT |
| L2 | NVIDIA CUDA Programming Guide [3], §4.2.3 Updating Instantiated Graphs and §4.2.3.2 Individual Node Update | NVIDIA_DOCUMENTATION_BACKED / DOCUMENTATION_BACKED_BEHAVIOR | Graph parameters are fixed when defined; executable node parameters can be explicitly updated | Capture a pointer to immutable A/g1, produce a separate A/g2 snapshot, omit the executable kernel-node pointer update | Adapted application fault using documented behavior; not an NVIDIA bug |
| C1 | Proposed here; no literature attribution | NEW_CC_CONTRACT_FAULT_MODEL | No claimed published operator | Host produces A/g2 but omits its transfer into the still-valid device allocation containing A/g1 | Nouvelle |
| C2 | Proposed here; no literature attribution | NEW_CC_CONTRACT_FAULT_MODEL | No claimed published operator | Route a valid B/g2 snapshot to a consumer whose contract requires A/g2; same type, dimensions, byte length and CUDA context | Nouvelle |

## Sources checked

[1] Qianqian Zhu and Andy Zaidman. *Massively Parallel, Highly Efficient, but
What About the Test Suite Quality? Applying Mutation Testing to GPU Programs.*
ICST 2020. DOI [10.1109/ICST46399.2020.00030](https://doi.org/10.1109/ICST46399.2020.00030).
[Author institutional PDF](https://pure.tudelft.nl/ws/portalfiles/portal/124438843/09159103.pdf),
PDF page 6, Listing 14; Table I on PDF page 8. Nine GPU-specific operators are
reported. Synchronization removal targets a kernel barrier such as
`__syncthreads()`. Our host event and stream operator is an adaptation, never
`IDENTICAL_TO_MUTGPU_OPERATOR`. The paper also notes schedule-dependent activation;
our deterministic adverse schedule does not estimate activation in natural runs.

[2] Mingyuan Wu, Yicheng Ouyang, Husheng Zhou, Lingming Zhang, Cong Liu and
Yuqun Zhang. *Simulee: Detecting CUDA Synchronization Bugs via Memory-Access
Modeling.* ICSE 2020, pp. 937–948. DOI
[10.1145/3377811.3380358](https://doi.org/10.1145/3377811.3380358).
[Author PDF](https://lingming.cs.illinois.edu/publications/icse2020b.pdf),
§3.2, pp. 941–942. Models thread memory accesses to detect synchronization bugs,
including races and barrier divergence. Used as motivation, not attribution
of any CC-Contract fault injection operator.

[3] NVIDIA, [CUDA Programming Guide 13.1.1, §4.2.3](https://docs.nvidia.com/cuda/archive/13.1.1/cuda-programming-guide/04-special-topics/cuda-graphs.html#updating-instantiated-graphs).
The pinned documentation explains graph-parameter updates and executable
kernel-node updates. An unchanged pointer does not freeze the contents of its
allocation: if that allocation is overwritten, replay may read new contents.
Therefore L2 retains both immutable, live snapshots and changes the intended
pointer. Reusing the old captured pointer is documented behavior, not a
vulnerability. Actual compilation targets the repository's pinned CUDA 12.8.1.

## Bounded, race-free adaptations

L1 healthy order: H2D(A/g1), record E1; H2D(A/g2), record E2;
wait E2; consume A. Fault: wait E1; consume A and synchronize the consumer;
then submit H2D(A/g2) and record E2. The harness deliberately schedules the
late producer after consumption to observe a legal stale read without a
simultaneous read/write race. This adds a controlled scheduling intervention
to the wrong event dependency. It does **not** demonstrate that merely deleting
one wait always returns stale data, nor measure uncontrolled race probability.
C1 differs: the generation-2 transfer is omitted rather than delayed.

All allocations remain alive until streams complete. L2 uses two snapshots of
one logical buffer identity; C2 uses different identities with compatible
allocations. No invalid pointer, premature free, overflow or kernel crash is a
positive detection. CUDA errors remain separate failures of this pilot's aim.

## Observation and claim boundary

The trusted host contract is frozen before selecting any fault. A consumer
reads identity, generation and payload words from the actual device input,
emits them with an independently checked integer computation, and the host
compares those observations with the contract. The detector receives no fault
name, requested activation or expected classification. Tags are instrumentation,
not cryptographic attestation; maliciously forged self-consistent inputs and
uninstrumented third-party kernels are outside this mechanism pilot.

The historical 140 jobs remain immutable and separate: 14,000 selected cases,
11,623 PASS and 2,377 pre-CUDA invalid cases. They are a bounded
HEALTHY / NO-INJECTED-FAULT baseline, not 14,000 successful CUDA executions and
not the healthy control group of this different, instrumented pilot.
