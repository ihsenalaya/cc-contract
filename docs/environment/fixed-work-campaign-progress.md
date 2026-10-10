# Fixed-work campaign: startup failed, local repair before retained-VM retry

The user resumed work with « continue le travaille » on 10 October 2026.
The **140 H100 jobs have not started**. Read-only inventory at 06:27 UTC
confirmed the original VM UUID and thirteen managed resources, with the VM
deallocated. Keep the VM, its OS disk and restart resources. Complete the
state reconciliation and fresh bounded plan before starting compute.

Preparation is complete: the protocol, 140-job harness and analysis are
versioned; both Kind CPU workers completed 140 successive four-case jobs
each. Independent review recomputed all **1,120 CPU cases** from the two
original archives. These remain CPU qualification evidence. Source commit
`4e54a4e590b56a691ca491b158ccfeb0697be32e` is published and its
[source CI passed](https://github.com/ihsenalaya/cc-contract/actions/runs/37997976604).

Both original CPU archives, inventories, audits and qualification logs are
backed up in private Azure storage: 70 explicitly selected files totaling
293,762,326 bytes. Every remote object was fully read back and matched its
local SHA-256 and length. Backup receipt SHA-256:
`b00902832a4311ad20d61b46db0ffd95bd5b1fe3070dacae760fd2e28ab80ba2`.

The first update-only resume plan was rejected before apply or VM startup:
Terraform observed fields populated after the original resource creation
(empty collections, the original NIC/VM and subnet/NSG attachments, MAC,
and the original subnet in the virtual network). Independent inspection
found thirteen update/no-op actions and zero creations, deletions or
replacements. The rejection and original binary plan remain preserved.

The **refresh-only state reconciliation is complete**. Its saved binary plan
passed independent review. All thirteen refreshed resource values and outputs
match the reviewed result; state lineage is unchanged and serial advanced
from 14 to 15. Azure readback confirmed the original VM remained deallocated.
No Azure resource was modified or started. Reconciliation receipt SHA-256:
`b0a2ffe6d56e2560a938947c4ab16b9cf5a8fdd62e086061998c6efdf057bd68`.

The state-reconciliation change passed **183 local source tests**, including
nine new controls, and secret scanning. It was published in commit
`a70c5909ada34e5d162d012a16771e55b2b3cb92`;
[source CI passed](https://github.com/ihsenalaya/cc-contract/actions/runs/38031584906).
The strict update-only guard remains intact.

The first actual retained-VM resume requested startup at 06:43:56.639245 UTC.
Azure Running was observed at 06:44:58.308515 UTC, but SSH timed out and the
finalization connection was refused. Host qualification and campaign execution
never began. The controller confirmed deallocation at 06:46:55.934619 UTC,
retaining the original VM, disk and all restart resources. The conservative
start-request-to-deallocation duration was **179.295374 seconds (2 min 59 s)**.
This does not establish the precise billing start. Network and identity
readbacks were coherent; the SSH failure's cause remains unconfirmed.

All 28 original files and symlink entries, including the failed empty export,
were preserved with identical hashes and targets. Preservation receipt SHA-256:
`564acd38cbed4e1f1092fa248d8b9eebfee1c11b6a0389e5d33fc57190ee7273`.
The local repair adds a bounded SSH readiness gate before qualification, checks
the current retained backend's guard and SSH outputs, and preserves the original
input/output receipts. **57 applicable local tests pass**, covering SSH readiness,
prior-attempt integrity, cumulative budget, state reconciliation, infrastructure
and cloud lifecycle. The actual preserved prior receipts also pass the retry
validator. Source CI must pass for the published repair before another start.

The requested scope remains 140 successive 100-selected-case jobs, immediate
deallocation on completion or failure, and resources retained. The retry must
count the first attempt against the original **USD 15 forecast / ninety-minute
VM allowance**. Its new bounded interval is at most **87 minutes**; local repair
while deallocated does not add H100 use. No GPU result is claimed yet.

Protected originals, qualification receipts and the timestamped pause
handoff and explicit resume inventory are outside Git in the project state
directory. No GPU campaign result is claimed at this preparation stage.
