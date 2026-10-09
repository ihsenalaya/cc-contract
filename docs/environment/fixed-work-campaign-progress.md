# Fixed-work campaign: paused at the user's request

At the user's request, work pauses until they resume. The **140 H100 jobs
have not started**. Keep the VM, its OS disk and restart resources, and do
not start GPU compute while this pause remains active.

Preparation is complete: the protocol, 140-job harness and analysis are
versioned; both Kind CPU workers completed 140 successive four-case jobs
each. Independent review recomputed all **1,120 CPU cases** from the two
original archives. These remain CPU qualification evidence. Source commit
`4e54a4e590b56a691ca491b158ccfeb0697be32e` is published and its
[source CI passed](https://github.com/ihsenalaya/cc-contract/actions/runs/37997976604).

The first update-only resume plan was rejected before apply or VM startup:
Terraform observed fields populated after the original resource creation
(empty collections, the original NIC/VM and subnet/NSG attachments, MAC,
and the original subnet in the virtual network). Independent inspection
found thirteen update/no-op actions and zero creations, deletions or
replacements. The rejection and original binary plan remain preserved.

On resumption, inspect and archive a **refresh-only state reconciliation**
for those exact attributes, checking all original identities, privileges
and network bindings. Preserve the strict update-only guard. Make a fresh
plan with a renewed expiry; the old plan must not be executed after its
deadline. Recheck local/source bindings and real deallocation before
starting the retained VM. The requested scope remains 140 successive
100-selected-case jobs, with the USD 15 forecast/90-minute window bound,
immediate deallocation on completion or failure, and resources retained.

Protected originals, qualification receipts and the timestamped pause
handoff are outside Git in the project state directory. No GPU campaign
result is claimed and no continuation is scheduled automatically.
