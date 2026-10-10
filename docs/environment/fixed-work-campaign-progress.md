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
validator. The SSH/budget repair was published in commit
`a845e1f01fd73477f50de4c2b014acee709c2b45`;
[source CI passed](https://github.com/ihsenalaya/cc-contract/actions/runs/38033067055).

The following read-only retry plan was rejected before any apply or startup.
Its sole drift entry changes the resource-group casing in the original OS disk
ID, in `os_disk[0].id` and `os_managed_disk_id`. Azure VM and disk readbacks
confirm the same actual VM UUID, attached disk and deallocated state. No other
resource value differs. The exact rejected plan is preserved with seven
unchanged file/symlink entries. Preservation receipt SHA-256:
`514f62e134c067dcee7f7a39ef67ef4222dc473acd96b4ba55c758905efbfca6`.
The earlier six-field normalization is not applicable to this separate drift.
A strictly bounded refresh-only state correction passed **70 applicable local
tests** (57 existing controls and 13 new disk-case controls). Independent source
review rejected 19 forbidden mutations. The disk's unique ID is rechecked
between planning and apply, along with its original VM attachment. The actual
refresh plan still requires independent review and verified state-only apply;
the regular resume validator continues to reject every unresolved drift entry.

The small original failure/repair proofs are backed up in private Azure storage:
30 explicitly selected originals, 318,767 bytes, and six provenance objects.
All 36 objects were fully read back and matched local SHA-256 and size; all
originals remain preserved. Final backup receipt SHA-256:
`e9840ecc40f6a819a71d18034d89abf67f5280674bd3231f73035c467b83b718`.

The requested scope remains 140 successive 100-selected-case jobs, immediate
deallocation on completion or failure, and resources retained. The retry must
count the first attempt against the original **USD 15 forecast / ninety-minute
VM allowance**. Its new bounded interval is at most **87 minutes**; local repair
while deallocated does not add H100 use. No GPU result is claimed yet.

Protected originals, qualification receipts and the timestamped pause
handoff and explicit resume inventory are outside Git in the project state
directory. No GPU campaign result is claimed at this preparation stage.
