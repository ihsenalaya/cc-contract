# Protocol v0.1 — initial local qualification (not frozen for comparison)

## E0: environment qualification

Local: record tools, Docker engine, host resources and Git/GHCR access; create a
dedicated Kind cluster with one control plane and two labelled CPU workers.
Check node health, pod placement, least-privilege service account, denied API
permissions and successful execution of the local OCI image on both workers.
Collect original logs, pod state, image IDs and cryptographic hashes outside Git.
Destroy/recreate only this cluster and rerun to check local reproducibility.

Azure inventory is read-only. Actual H100 E0 requires a costed approved temporary
window, pinned confidential image and a verified provisioning/cleanup mechanism.
GPU attestation, real copies, calculation references and inference cannot be
passed by fixtures. Driver/CC status is necessary but is not inference evidence.

## E1: development oracle qualification

Initial corpus: 24 legal correct cases, 24 controlled semantic mutants and 12
invalid cases. Each group and seed is recorded, without independent-evaluation
claims. A mutant changes an observation at the adapter boundary: payload
corruption, stale payload, or stale generation. Correct metadata/payload checks
are exact integer comparisons. Invalid cases exercise missing synchronization,
premature free and shape mismatch. Every expected category must match, with
no false positive among legal model cases; malformed input must fail closed.

These checks establish only the operation of this bounded CPU oracle/validator.
They do not estimate sensitivity to real defects. Floating point calibration,
repeat variability, real-GPU false positives and indeterminate classifications
remain required before E1 may be COMPLETE or oracles frozen for comparison.

## E2: bounded operation contracts

IR v1 specifies allocations, integer host writes with increasing generations,
stream-ordered asynchronous copies, events/waits, stream synchronization,
host observations and frees. The conservative validator checks C0 support/shape,
C1 visibility, C2 outstanding uses and C3 generations. The CPU adapter defers
copies until synchronization, preserves stream/event order and uses an independent
data representation from the validator's dependency analysis.

Implemented generator subset: T01 copies, T02 reuse, T03 event dependency, T05
generation metadata. T04 double buffering and T06 boundary matrices still need
dedicated generators. T07 mapped memory and T08 graph/replay are UNSUPPORTED in
this version. C4 graph replay is not implemented. CUDA permits more schedules
than this conservative model; rejection here does not establish CUDA illegality.

No undefined CUDA behavior is part of the main campaign. Controlled mutants
must never be implemented by provoking invalid memory lifetimes or races.

## Later experiments and statistical commitments

E3: separate development, documented historical incidents and reserved evaluation
sets; H08/H09 remain historical reports with unconfirmed causes until reproduced.
E4: B1 independent, B2 valid random stateful, B3 nontemporal guidance, B4 full;
initial proposal 20 independent 10-minute campaigns each. E5 ablations may reuse
E4 only with documented justification. E6 up to eight representative traces,
five paired attempts each, 60 s per attempt. E7 component paths then Transformers
Qwen2.5-7B-Instruct when qualified; 24 prompts at 32/128/512 tokens, fixed shared
inputs and continuation when comparing multiple steps. E8 is conditional on
characterized anomalies, initially ten paired blocks of 24 requests.

Before comparative campaigns, freeze defect equivalence rules, primary metrics,
experimental units, independent seeds, budgets, order randomization, censoring
of nondetections, minimum practically useful effect, confidence methods and
multiple-comparison handling. Use pilot estimates for precision/power planning;
do not run until a favorable p-value appears. Counts and times from tokens of
one run are not independent runs. A negative or uncertain result is valid;
claims of superiority require measured, practically relevant evidence.

No E0–E8 experiment is COMPLETE solely because a subset of CPU tests passed.
Every state transition in experiments/status.json requires an evidence link.
