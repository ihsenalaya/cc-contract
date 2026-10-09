# Cloud model H100 pilot — concrete scope requiring approval

The first approved E0 window is closed and its 13 resources were destroyed.
This next window is a prerequisite for completing real E0/E1/E2/E7 qualification.
No further GPU allocation or comparative campaign has been approved.

## Locally verified preparation

[The evidence manifest](../../results/manifests/cloud-pilot-local-qualification.json)
records 62 passing source tests, two passing Terraform mock plans, and actual
Azure Blob downloads on both Kind CPU workers. The new downloader image was
built locally from commit `0c6790e877ac3f74d2910dedbab8ac017d8fb68b`, qualified
on both workers, then published to GHCR by its immutable digest. The scientific
CUDA/IR/Torch images retain their previously verified immutable digests.

The official Linux Azure CLI is pinned to 2.78.0 with resolved dependencies in
`scripts/requirements-azure-cli-linux.txt`. `scripts/setup-azure-cli-linux.py`
recreates the isolated client and reuses the existing authorized native session.
Tokens, profiles, SSH keys, plans, state and original evidence remain in protected
Linux user state. No GPU operation depends on the failing Windows CLI relay.

Read-only checks on 2026-10-09 found zero project VMs, 40 available NCC-family
cores, 82 regional cores and no returned H100 SKU restriction in East US 2.
Actual allocation capacity remains unguaranteed.

## Infrastructure and workload

The proposed window contains one confidential `Standard_NCC40ads_H100_v5`
and 14 temporary resources: the previous 13-resource infrastructure plus a
VM managed-identity read assignment at the dedicated model container only.
The permanent artifact store is preserved. The community image remains pinned
to `2204.20260928.0`; experiments are blocked if the host does not have driver
`595.91.07`, kernel `6.8.0-1066-azure-fde`, CC ON/PRODUCTION and secure boot.
No reset, MIG, downgrade, AKS or driver installation is involved.

The VM downloads the 14 prepared model/corpus files directly from private Azure
Blob using its own managed identity. Each byte count and SHA-256 is verified
before inference. This guest identity path still requires actual VM verification;
Kind verified the downloader with the existing user's Azure authorization.
The 15 GB of weight shards are not restored to the PC.

After host qualification the prepared run executes:

- 54 CUDA reference observations, independently reviewed after release;
- the 96 bounded T01–T08 IR cases with original detailed observations; explicit
  unsupported capabilities remain UNSUPPORTED and API failures remain failures;
- 18 embedding/metadata, linear and reduced-attention component records, using
  the existing independent numerical references;
- 24 frozen Qwen2.5-7B-Instruct prompts at lengths 32/128/512, paired synchronous
  and asynchronous transfers with identical forced continuations, preserving
  complete logits/hidden-state artifacts and exact generation metadata.

Paired model agreement establishes a diagnostic result, not independent absolute
model correctness. Local GPU HMAC verifier receipts do not establish independent
quote/NRAS validation. Missing qualification prevents oracle/protocol freeze.

## Duration, cost and cleanup

One H100, at most two hours in this window; proposed authorization **USD 20**.
The Azure Retail Prices API retrieved on 2026-10-09 gives Linux regular
pay-as-you-go **USD 6.98/hour**, hence USD 13.96 for two hours of compute.
The remaining allowance covers temporary disk, IP, workflow and transfers.
Contract prices, tax and Azure API delays can affect billing; this is a costed
spending plan, not an enforceable invoice ceiling.
[Official pricing API documentation](https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices).

An independent minute-resolution expiry workflow is provisioned before the VM.
The runner also finalizes partial evidence on failure, verifies the exported
archive, immediately deallocates and confirms the power state. It destroys only
this window's temporary resources after durable evidence verification. An export
failure still releases compute and retains the recovery disk. The actual expiry
branch against an allocated GPU is a remaining validation, not a mock-test claim.

The saved Terraform plan, workload bundle and host script are hash-bound. The
read-only plan receipt will record exact changes and absolute expiry. No apply
occurs before user approval. An expired plan must be regenerated before execution.

## Work remaining beyond this pilot

E4/E5 retain the declared 20 blocks × 7 policies × 600 seconds: 140 GPU jobs,
23 hours 20 minutes, approximately USD 162.87 of compute at the retrieved rate,
before provisioning/qualification time and other charges. These campaigns need
oracle/protocol freeze and their own approved costed schedule; this pilot does
not replace their budget. Original H08/H09 evidence/configurations are still
missing for E3. E6/E8 depend on a technically characterized real anomaly and may
be inapplicable if none is established. Azure kubeadm integration remains to be
implemented and qualified; this pilot uses the prepared standalone containers.
