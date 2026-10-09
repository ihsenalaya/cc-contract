# Actual cloud-model H100 pilot — 2026-10-09

The approved USD 20 / maximum two-hour window `pilot-cloud-1009c` completed.
Its 14 temporary resources were created and destroyed. The VM was confirmed
`PowerState/deallocated` at **16:24:17 UTC** before local review. Fresh Azure
inventory found zero project VMs, the temporary group absent and Terraform state
empty. The permanent private model/evidence store remains available.

The new VM had H100 NVL / 95,830 MiB, host driver **595.91.07**, kernel
**6.8.0-1066-azure-fde**, CC **ON / PRODUCTION** and secure boot. Its managed
identity downloaded and SHA-256 verified all **14 model/corpus files**, totaling
**15,242,896,869 bytes**, directly from Azure. Local weight shards were not restored.
The pinned Torch container actually ran **PyTorch 2.8.0+cu128 / CUDA 12.8**.

| Workload | Actual result | Offline verification |
|---|---|---|
| Native CUDA reference | 54 observations passed | Every integer payload/generation independently recomputed |
| T01–T08 IR | 96 cases, 252 observations passed | Original scenarios/payloads independently recomputed; mapped memory and graphs supported |
| Torch components | 18 records passed | Embeddings/tags exact; linear references recomputed with rational arithmetic; attention with Decimal100 |
| Qwen2.5-7B-Instruct | 24 prompts, 48 paths, 144 paired steps | All 22,413,312 logits/hidden-state element comparisons exact; stored physical tokens and generation tensors checked |

The linear maximum absolute error was zero. Reduced-attention maximum absolute
error was **2.2126183468751393e-8**, below the predeclared bounded-input threshold
**1.406133025706193e-6**. The Qwen audit checked the original 48 tensor artifacts,
their hashes, full paired logits/hidden vectors and frozen shared continuation.
The reviewer uses the standard library and accepts only the declared tensor
serialization layout; it does not require installing another large Torch image.

CPU MAA RS256 signatures and selected claims were verified against the fixed
trusted issuer and the actual applied VM identity. GPU outputs again contained
local HMAC verifier receipts with all 16 reported checks true. Their hardware
quote/NRAS chain was **not independently reverified**. An enabled minute-resolution
expiry guard was read back from Azure; actual deallocation in this run came from
the normal runner, so the independent expiry branch against an allocated H100
remains untested.

**No real defect was discovered in this pilot.** These are bounded qualification
observations from one campaign per workload. Exact paired model agreement checks
path coherence; it does not establish absolute mathematical correctness of the
model or fix the historical vLLM H08/H09 reports. No speedup, statistical
superiority, independent-evaluation or complete E0–E8 claim follows from this run.

The original **94,842,752-byte** archive contains **84 verified evidence files**.
Its SHA-256 is
`3f2d2641bbf3c8d2dc1fb625379bbd27a703d52fff1563ad8663336d671fb698`.
The archive and six collection/review/cleanup receipts were uploaded to private
Azure evidence storage and each reread completely to verify SHA-256 and size.
Original data stays outside Git; [the public manifest](../../results/manifests/cloud-pilot-gpu-qualification.json)
links results, images, raw hashes, storage receipts and remaining limitations.

The final source suite passed **66 tests**. New audit rejection checks cover
truncated storage, nonfinite tensor values and unauthorized pickle callables.
The applied-state/VM-identity snapshot step is now part of the controller, so
future cleanup retains the identity needed for post-destruction attestation review.

## Remaining completion work

- E0: independent GPU quote/NRAS verification, real allocated-state expiry test,
  and Azure kubeadm integration/recreation qualification.
- E1: wider oracle calibration, independent-campaign variability and oracle freeze.
- E2/E7: reserved independent evaluation; absolute model correctness is not
  established by the diagnostic pair comparison.
- E3: original H08/H09 logs and exact configurations, then qualified reproductions.
- E4/E5: freeze the protocol/oracles and approve the complete 140-job / 23h20
  comparative schedule, including provisioning overhead and auxiliary charges.
- E6/E8: conditional on a characterized real anomaly; this pilot supplies none.
