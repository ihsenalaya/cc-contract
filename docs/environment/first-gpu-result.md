# First real H100 window — 2026-10-09

Result: **partial E0 qualification with 54 independently checked CUDA observations**.
The approved single-H100 window was executed automatically. Evidence was exported
and its checksums verified, Azure confirmed deallocation at 10:49:31 UTC, and
Terraform destroyed all 13 temporary resources. Azure confirmed the resource
group no longer exists; the final Terraform state has zero resources.

| Item | Observed result |
|---|---|
| Environment | East US 2, Standard_NCC40ads_H100_v5, NVIDIA H100 NVL |
| Pinned image | cgpu-NCC-2204-base-image/2204.20260928.0 |
| Preserved host software | NVIDIA 595.91.07; kernel 6.8.0-1066-azure-fde |
| CC / Secure Boot | CC ON, PRODUCTION, SecureBoot enabled |
| CPU attestation | Official command exit 0; RS256 signature independently verified with MAA keys; VM identity matches Terraform; selected SNP/Secure Boot/debug claims pass |
| GPU attestation | Official command exit 0; NVIDIA local verifier reports successful hardware report, nonce, certificate, signature and RIM checks |
| Native CUDA | 54 PASS observations; exact expected and observed integer arrays independently recomputed in Python |
| Host PyTorch | Import fails: torch is not installed; PyTorch GPU/inference qualification remains required |
| Cleanup | Verified archive retained privately; VM deallocated; 13 resources destroyed; no project Azure resources remain |

The CUDA records comprise T01=3, T02=9, T03=3, T05=9, T06=27, and integer kernel
reference=3. Three repeats belong to **one qualification execution**. They are
not 54 independent campaigns. T04/T07/T08, floating-point inference, the complete
IR-to-CUDA adapter and comparative E3–E8 campaigns were not executed.
No discrepancy was found in these bounded cases; no superiority claim is made.

The VM took **30m25s** to provision. An earlier SSH probe timed out and the disk
remained Updating during preparation. The cause of the excess delay is unknown.
Microsoft's creation guide gives an indicative 15–20 minutes; future windows
must include startup time and use a declared provisioning cutoff.
[Microsoft creation guide](https://github.com/Azure/az-cgpu-onboarding/blob/main/docs/Confidential-GPU-H100-VMI-Creation-CLI.md).

The GPU tokens identify LOCAL_GPU_VERIFIER and use HS256. These are receipts
from the installed local hardware verifier, not independently authenticated NRAS
tokens. The quote/RIM verification checks reported by that tool were all true.
Independent replay of an exported GPU quote, remote attestation, and MAA provider
TEE/signing-key binding verification were not performed. This scope follows
[NVIDIA's distinction between local and remote verification](https://docs.nvidia.com/attestation/quick-start-guide/latest/attestation-examples/hopper_single_gpu.html).

Qualification recorded exit 1 because host PyTorch was absent. The original
lifecycle wrapper returned 0 after successful collection/cleanup instead of
propagating that qualification exit. The wrapper is now corrected; CPU regression
tests verify nonzero propagation and cleanup after failed qualification. The fix
was not deployed again. Post-run source/review checks pass **24 unit tests**.

The cloud expiry workflow was Enabled and three successful pre-expiry timer runs
were observed. Its actual deallocation branch and actual H100 recreation remain
NOT_RUN. The authorization was USD 20 for at most two GPU hours; actual subscription
billing is not yet available. No billed-hour or invoice total is fabricated.

Original Terraform logs/state, attestation tokens and guest evidence remain in
protected Linux state storage. The [sanitized evidence manifest](../../results/manifests/first-real-gpu-qualification.json)
links their hashes and the review scope. Every failed check remains in the
[incident history](../incidents/incidents.jsonl).
