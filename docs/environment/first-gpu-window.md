# First H100 window — proposal requiring approval

No H100 is currently deployed. No Azure resource was created during preparation.
Read-only inventory found regional total CPU quota 82, with 40 free NCC-family
cores in East US 2 and no SKU restriction returned. Catalog/quota checks do not
guarantee capacity. Existing unrelated T4/CPU VMs and other resources are excluded.

## Concrete infrastructure

The prepared Terraform plan contains **13 creates, zero updates, zero deletes**:
one resource group, VNet, subnet, NSG, subnet association, public IP, NIC,
one confidential `Standard_NCC40ads_H100_v5`, and an independent expiry workflow
with recurrence, action, narrowly scoped custom role and role assignment.

The community image is pinned to `cgpu-NCC-2204-base-image/2204.20260928.0`.
The VM uses secure boot, vTPM and `DiskWithVMGuestState`, with a 128 GiB standard
SSD OS disk. SSH permits only the current approved client IPv4 /32. The workflow
is created before the GPU and checks the approved absolute expiry every minute;
it requests Azure deallocation while retaining the OS disk. Real workflow behavior
and real H100 recreation are not validated by the passing mock test.

Source: [Microsoft's confidential GPU onboarding](https://github.com/Azure/az-cgpu-onboarding/blob/main/docs/Confidential-GPU-H100-VMI-Creation-CLI.md).

## Scope of the first run

Inspect the existing software supplied by the new official community image;
preserve its kernel and driver. Collect kernel, NVIDIA state, CC ON/PRODUCTION,
secure boot, CPU/GPU verifier outputs and verifier hashes. Inspect PyTorch when
present. Missing tools/features are recorded rather than installed speculatively.

Only after critical CC/attestation command checks succeed, run the locally built,
Kind-qualified CUDA image by its GHCR digest. It performs **54 bounded legal
observations**, including three repeats of simple copies, buffer reuse,
stream/event dependencies, metadata generations, boundary sizes and an integer
affine reference kernel. A mismatch is initially INCONCLUSIVE with oracle FAIL,
pending replay/diagnosis. CUDA API errors are INFRA_FAILURE.

This is an initial E0 qualification subset. It is not the complete GPU adapter
for CC-Contract, does not validate floating-point inference and does not execute
E4 comparative campaigns. Attestation reports and their trusted verifier chain
must be reviewed before announcing full qualification.

## Release, preservation and costs

`scripts/azure-window.py run` orchestrates the approved apply, qualification,
collection and cleanup. Copy the evidence archive to protected Linux user state
storage, verify every entry listed in its SHA256SUMS, then immediately deallocate
and confirm `PowerState/deallocated`. Destroy the temporary Terraform resources
only after the verified archive is durable. Failed export still releases compute;
the disk remains for recovery, with a declared ongoing storage cost. Original
archives and failed attempts must never be overwritten. No reboot/reset is used.

The independent expiry is a fallback, with at least one-minute polling granularity
and Azure API delay; immediate release by the runner remains the normal path.
An outage or denied Azure operation can delay deallocation and must be recorded.
No automation can guarantee an instantaneous Azure control-plane response.

Public Linux pay-as-you-go rate retrieved on 2026-10-09: **USD 6.98/GPU VM hour**.
At most two hours of allocation gives **USD 13.96 compute** at that list rate.
Proposed total authorization: **USD 20** including a margin for OS disk, public
IP, workflow actions and transfer; taxes and contract-specific billing may differ.
This is a spending plan, not a guaranteed invoice ceiling. Abort rather than
silently extending the approved allocation. Destroy promptly to avoid residual
charges. See [queried pricing evidence](../../results/manifests/azure-cost-proposal.json)
and [Azure Retail Prices API](https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices).

The private saved plan, SSH key and state are under Linux user state storage;
they are never published. Plan expiry is absolute: regenerate an expired plan
before execution, preserving the reviewed scope/budget and the previous plan.
Creating a second GPU, increasing allocation/budget or running long comparative
campaigns requires a separate approval.

## Verified prerequisites and remaining risk

Local model/source checks, Kind jobs, cluster recreation, cross-worker network,
CUDA compilation/CPU reference/no-device rejection and Terraform schema/mock
planning have real local evidence. A real authenticated Terraform plan completed
without resource changes. The new VM's driver/tool compatibility, real capacity,
attestation onboarding, independent cloud expiry and actual CUDA execution remain
to be verified. Failures must stop compute and retain evidence rather than be
converted to PASS. No H100 scientific results exist yet.
