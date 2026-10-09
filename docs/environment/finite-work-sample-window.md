# Finite-work H100 timing sample — provisioning proposal

Status: local checks completed and saved read-only plan verified; USD 15 / 90
minutes approved by the user. Stop and retain the VM until the user's decision.

Window `work-sample-1009b`: thirteen creations, zero changes to existing
resources, zero resources created. Saved plan SHA-256:
`74397e689b9a7cc87a87f817412dafcb29f1ce264199c2439279e602864a37a5`.
Expiry: 2026-10-09 21:38:20 UTC. Apply requires at least eighty minutes remaining.
Local evidence: [qualification manifest](../../results/manifests/finite-work-sample-local-qualification.json).
All 104 unit tests and both Terraform mock checks passed; both Kind workers
completed fourteen four-case functional jobs. Independent review recomputed
112 cases, 100 passing and 12 invalid. The 100-case storage projection completed
all fourteen jobs: approximately 599 MiB raw, 2.43 GiB with the planning margin,
and a largest per-job bound of approximately 356 MiB. These are CPU preparation
checks; H100 timings are still unmeasured.

Measure the actual time needed for a declared amount of work. The earlier
time-budgeted sample was partial and cannot supply timings for all methods.
The [new development protocol](../methodology/finite-work-throughput-pilot.md)
preserves those earlier results and the reserved comparison schedule.

| Item | Proposed scope |
|---|---|
| Hardware | One temporary Standard_NCC40ads_H100_v5, East US 2 |
| Configuration | CC ON/PRODUCTION; driver 595.91.07; kernel 6.8.0-1066-azure-fde |
| Fixed work | Seven methods, two development jobs each, exactly 100 selected cases per job including invalid cases |
| Execution | Fourteen successive jobs, one executor; stop each at its case quota |
| Safety guards | 120 seconds per campaign at loop boundaries; 30-minute sample command guard; stop following jobs after any failure or interruption |
| Storage | 1 GiB per job, 8 GiB total traces, 2 GiB free reserve; deterministic CPU volume check required before planning |
| Expected cloud cycle | Approximately 40–75 minutes; estimate includes earlier roughly 30-minute VM creation, not a measured sample duration |
| Absolute expiry | 90 minutes from plan creation; independent cloud deallocation guard |
| Retail compute estimate | USD 6.98/hour; USD 10.47 for 90 minutes |
| Proposed total budget | USD 15, including USD 4.53 allowance for temporary disk, IP, guard and evidence transfer/storage |
| Temporary resources | One VM; saved Terraform plan must contain only thirteen creations and no changes to existing resources |
| Finish | Export and hash-verify originals, immediately confirm deallocation, retain the VM and disk until the user's decision |

The retail rate and read-only quota inventory were checked at
2026-10-09 19:54–19:55 UTC: zero project VMs, regional usage 0/82 vCPUs,
target-family usage 0/40 vCPUs. Quota does not guarantee allocation capacity.
The price comes from the official [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices).
USD 15 is a forecast, not a billing-system hard cap. The minute-resolution
expiry guard initiates asynchronous deallocation; record its confirmed completion.
Starting apply requires at least eighty minutes remaining in the saved plan.

The 120-second campaign guard is a safety limit, not the completion criterion
or a predicted duration. The existing runner checks its guard between cases;
a case already executing can extend that interval. The host and cloud guards
provide independent bounds. A job that misses its quota remains partial and
does not support a completed-work projection.

Reuse the already qualified immutable CUDA and IR images. Mount the exact
hash-bound wrapper and specification; download no model or Torch image.
Host, CPU/GPU attestation, CUDA reference and full 96-case IR qualification
must succeed before the sample. Local CPU and Kind checks establish pipeline
behavior only. They do not validate CUDA or confidential-computing operation.

The recap reports both measured durations for every method, passing/invalid
cases, candidate draws, coverage and original trace bytes. Conditional
projections for 100, 1,000 and 10,000 selected cases per job use the complete
job interval, including final hashing and manifest creation. For the proposed
twenty-block/seven-method matrix, sum the projected times for all 140 jobs.
Two jobs give an observed range, not a confidence interval or a scientific
sample-size justification. Longer runs may scale differently.

Report the full elapsed cloud cycle, with provisioning, qualification, sample,
export and confirmed stop. Report preparation, offline review,
verified Azure backup, publication and any user waiting separately. Stop the
H100 before CPU review and keep the VM, disk and restart resources while the
user decides. Preserve the disk if export fails while still releasing compute.
Destruction requires a later explicit user instruction. Deallocation releases
the hardware allocation; retained disks and networking can still incur charges,
as explained in [Azure's billing states](https://learn.microsoft.com/en-us/azure/virtual-machines/states-billing).

Before apply: pass all applicable local checks, both Kind worker checks, the
independent original CPU trace review and the full-schedule storage projection;
bind the final hashes into a saved read-only Terraform plan; obtain approval
of this concrete USD 15 / 90-minute window, as required by prompt.txt and
AGENTS.md. No full E4/E5 campaign, inference campaign or additional GPU is
included. E6/E8 remain conditional on characterized anomalies, and GPU quote
authentication and other outstanding E0 criteria remain separate work.
