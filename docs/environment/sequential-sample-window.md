# Sequential H100 sample — provisioning proposal

Status: locally qualified and explicitly approved by the user for USD 15 / 90 minutes; execution pending.

The user requested a sample, explicitly removed parallel GPU jobs, requested
immediate shutdown before deciding on further work, and prioritized total
elapsed time. The bounded [development protocol](../methodology/sequential-throughput-pilot.md)
implements those constraints. This is not the full E4/E5 comparison.

| Item | Proposed scope |
|---|---|
| Hardware | One temporary Standard_NCC40ads_H100_v5 in East US 2 |
| Configuration | H100 NVL, confidential mode ON/PRODUCTION, existing driver 595.91.07 and kernel 6.8.0-1066-azure-fde |
| Sample | Two development blocks of seven methods; fourteen successive 60-second jobs |
| Campaign budget | 14 minutes; report actual last-case and orchestration overhead |
| Expected cloud cycle | Approximately 50-75 minutes, including the roughly 30-minute creation observed in both earlier windows; this is an estimate |
| Absolute expiry | 90 minutes from saving the Terraform plan, never extended during execution |
| Compute retail estimate | USD 6.98/hour; USD 10.47 for 90 minutes, excluding other charges |
| Total proposed budget | USD 15 including a USD 4.53 allowance for temporary disk, public IP, guard and evidence storage/transfer |
| Temporary resources | Thirteen creations, no updates/deletions of existing resources; verified in the saved plan |
| Finish | Export and hash-verify originals, confirm deallocation, then destroy this window's temporary resources |

The retail Linux rate was freshly retrieved from the official Azure Retail
Prices API. Windows, Spot and Low Priority meters are excluded. The API exposes
retail estimates rather than an actual subscription invoice; see Microsoft's
[API documentation](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices).
Read-only preflight found zero project VMs, 0/82 regional vCPUs, 0/40 vCPUs
in the target family, and no listed restriction on this SKU. It does not
guarantee physical allocation capacity.

The 90-minute expiry triggers a minute-resolution cloud guard; Azure deallocation
itself is asynchronous. Record the actual confirmed stop time. USD 15 is a
forecast including an allowance, not a billing-system hard cap. Normal completion
releases compute immediately without waiting for expiry. Apply also requires at
least 75 minutes remaining, avoiding a late start with an inadequate time budget.

Pull only the already qualified immutable CUDA and IR images. The model and
previous evidence stay on private Azure storage; this window downloads no
Qwen weights and no Torch image. Mount only the hash-bound sample specification
and harness. Every gate must pass before the sample starts. No MIG, MPS,
AKS, GPU reset, kernel update or driver installation is involved.

The cycle records the complete duration from apply through confirmed deallocation
and destruction; local preparation, offline review, backup and user waiting are
reported separately. The GPU is deallocated before the long independent CPU
review. It remains unallocated while the user assesses the result. A failed
export still releases compute and preserves the disk for recovery.

CPU MAA signature review and local GPU attestation receipts are retained. This
sample does not complete independent GPU quote/NRAS verification, allocated-state
expiry testing, Azure kubeadm integration, or any other remaining E0-E8 criterion.

Before apply, require completed local checks, both Kind CPU worker checks, the
read-only saved plan with bound script/spec hashes, and user approval of this
USD 15 / 90-minute window. The preceding USD 20 pilot was already completed
and destroyed; it does not authorize a new allocation.
