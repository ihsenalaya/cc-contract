# Scientific contribution and claim boundary

Target: **Runtime Semantic State-Continuity Verification for Confidential GPU Execution**.
Q1 is a publication ambition, not a demonstrated quality or acceptance claim.

1. **C1 — HDSC model.** An application-owned relation between logical buffer identity,
   monotone generations, producer, stream/event epochs, consumer and payload.
2. **C2 — Runtime verifier.** An online checker consumes intents and executed bindings
   incrementally. It does not take a complete permitted trace or fault label.
3. **C3 — Confidential-H100 evaluation.** Existing bounded feasibility evidence plus
   separately reserved detection, dynamic workload and real-AI overhead evaluations.
   The [supported bounded RQ2–RQ4 matrix](../environment/hdsc-final-evaluation-result.md)
   is now measured and independently audited. Compute Sanitizer comparison is
   unavailable on the tested CC host; this limits the comparative claim.

The gap is **partially supported, not an established novelty theorem**. CUDA status
and the documented sanitizer checks are not application identity/version contracts.
An exact output oracle can nevertheless detect all output-changing faults in our
integer workload. Equal output does not imply equal consumed state. That distinction
is useful only where the application actually requires identity/version continuity.

The [related-work matrix](related-work-matrix.md) leaves unverified LGT4CG details
unknown. We cannot claim it fails on all dynamic execution, nor that HDSC is the
first state/version monitor. Comparison of trust assumptions is essential: our
trusted host adapter is a larger assumption than monitors protecting against an
untrusted runtime. No security superiority or new NVIDIA vulnerability is claimed.

Random/structural/state-aware generation is deferred, with zero runs in this
proposal. It would answer a secondary search-efficiency question, not RQ2–RQ4.
