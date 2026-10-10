# Fixed-work campaign: complete audited matrix, H100 deallocated

All **140 successive GPU jobs × 100 selected cases** passed independent raw-case
recomputation. This completes the bounded v0.3 E4/E5 matrix: twenty paired
independent blocks, seven methods, 14,000 selected cases and 164,000 candidate
draws. Invalid selected cases were rejected before CUDA. See the
[result and method table](fixed-work-campaign-result.md) and
[hashed result manifest](../../results/manifests/fixed-work-campaign-gpu-result.json).

The H100 is **deallocated**. Independent Azure readback confirmed the same
VM and attached OS disk, with thirteen managed resources retained and zero
destroyed. Current start request to confirmed deallocation took **56 min 20 s**;
including the earlier failed zero-work startup, **59 min 19 s**, within the
original ninety-minute allowance. These are measured lifecycle intervals,
not an independently established billing start or invoice amount.

All 597 original collected files match their hash inventory. The private Azure
archive was fully read back and matched SHA-256 and length. The independent raw
audit, host review, worker proofs and reviewed public result files are also
backed up with full remote readback verification. Local originals remain.

Host review passed the pinned kernel/driver, CC production, Secure Boot, CPU MAA
RS256 signature/VM claims, CUDA references and the 96-case IR qualification.
Independent GPU hardware quote/remote-token authentication remains unverified.
The complete E0–E8 project, broad numerical-oracle calibration and adequate
statistical power are not established by this bounded result. Zero candidate
failures establishes no superiority of B4 or absence of all possible defects.

All result review occurred on CPU after deallocation. The portable auditor and
its scientific result parity were qualified against both original Kind archives;
219 local source tests and published source CI passed. See
[offline reproduction](../reproducibility/fixed-work-offline-audit.md).

The earlier failed restart consumed 179.295374 seconds and executed zero jobs;
its SSH failure cause remains unconfirmed. Its originals are preserved. The
qualified retry added bounded Running-plus-SSH readiness and a strictly reviewed
state-only OS disk ARM-ID casing refresh, preserving the same disk unique ID.
The successful retry did not change the driver, kernel, CC or scientific sources.
Earlier operational checkpoints remain in Git history and the
[incident ledger](../incidents/incidents.jsonl).

**Any further H100 allocation or restart requires the user's new explicit
approval.** Continue offline preparation only until then. See
[remaining H100 work and blockers](remaining-h100-experiments.md).
