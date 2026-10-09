# Sequential H100 development sample — 2026-10-09

The approved USD 15 / maximum 90-minute window `sample-seq-1009a` produced a
**partial sample**. Only the first B1 job ran. It stopped at the predeclared
256 MiB trace limit after **50.391845647 seconds**, before its 60-second budget
finished. The other thirteen jobs were not launched. The stop was a storage
policy limit, with no disk-full condition or GPU failure reported.

The VM was confirmed **PowerState/deallocated at 19:31:01.897586 UTC** before
independent CPU audits. **All thirteen temporary resources were destroyed.**
Fresh verification at **19:36:56 UTC** found zero project VMs, an absent temporary
group and custom role, and empty Terraform state. The permanent Azure
model/evidence store remains available.

| Observed first job | Independently verified result |
|---|---:|
| Generated proposals | 2,063 |
| Legal CUDA cases passing exact payload/generation checks | 1,752 |
| Invalid proposals rejected before CUDA | 311 |
| Physical observations recomputed | 1,973 |
| Candidate FAIL / UNSUPPORTED / infrastructure failures | 0 / 0 / 0 |
| Passing cases per actual campaign second | 34.76753 |
| Original trace bytes | 268,507,365 |

The raw trace exceeded its 268,435,456-byte bound by **71,909 bytes** because the
last complete record was retained. This respects the declared one-record
overshoot. The original campaign is `INTERRUPTED`; the sample is
`STOPPED_RESOURCE_LIMIT`; independent review is `PARTIAL_SAMPLE_AUDIT`.
Every original case, seeded B1 proposal, count and observation was recomputed.
This verifies the retained partial evidence, without promoting it to a completed
campaign. No real defect was discovered.

## Qualification and elapsed time

The confidential H100 retained driver **595.91.07**, kernel
**6.8.0-1066-azure-fde**, CC **ON / PRODUCTION** and secure boot. Before sampling,
native CUDA **54 observations** and T01–T08 IR **96 cases / 252 observations**
passed; offline reviewers independently recomputed both. CPU MAA RS256 signature
and the actual applied VM identity were verified. All 16 local GPU verifier
checks were reported true; their HMAC receipts and hardware quote/NRAS chain
were not independently authenticated. E0 remains partial.

| Phase | Measured elapsed time |
|---|---:|
| Observed local preparation, 18:23:41–18:50:28.125896 UTC | At least 26 min 47.126 s |
| Terraform apply, including VM creation | 32 min 58.485 s, monotonic |
| Actual campaign loop | 50.392 s |
| Complete sample harness, including initialization/close and evidence checks | 53.293 s |
| Before apply, 18:53:17.444593 UTC, to confirmed deallocation | **37 min 44.453 s**, UTC subtraction |
| Complete controller cycle through destruction, ending 19:36:12.776304 UTC | **42 min 50.959 s**, monotonic |
| Offline host/IR audit, after deallocation | 58.364 s |
| Offline sample audit, after deallocation | 57.967 s |
| First observed preparation to final verified Azure evidence backup, 19:37:51.749067 UTC | **At least 1 h 14 min 10.749 s**, including waiting and overlapping work; Git publication excluded |

The two CPU audits overlapped, and backup overlapped destruction/review, so
these durations must not be added as successive stages. The complete backup
operation took 355.913 seconds, including its wait for destruction; 19 files
totaling 111,345,545 bytes were remotely verified. Preparation began before its first recorded timestamp; that measurement
is a lower bound. The cloud cycle includes provisioning, pulls, qualification,
the sample, export and deallocation. VM creation alone took about **31 min 19 s**;
this control-plane duration is not a measurement of billed compute time.
The complete controller cycle additionally includes destruction. Its UTC
timestamp interval is **42 min 55.332 s**; the monotonic receipt measures
**42 min 50.959 s**. The 4.372-second clock difference is retained rather than
adjusting either measurement. CPU audits, final receipt backup and user waiting
are tracked separately because they can overlap other phases. The
[public result manifest](../../results/manifests/sequential-sample-gpu-result.json)
links the final cleanup and timing receipts. The controller reports
`CalledProcessError` because the sample's partial exit propagated through
qualification; verified export, deallocation and destruction still completed.

The window-scoped ActualCost query returned **no rows**. Actual charges are
therefore **unknown**, not USD 0; USD 15 was the approved forecast, not an
invoice. Azure distinguishes provisioning from power/billing states, and
deallocation stops instance billing while retained disks/networking can still
incur charges. [Microsoft billing states](https://learn.microsoft.com/en-us/azure/virtual-machines/states-billing).
Cost data arrives asynchronously and is estimated until invoiced.
[Microsoft Cost Management data](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/understand-cost-mgt-data).

## Evidence and limits

The **111,216,691-byte** original archive contains **38 verified files**, remains
outside Git, and was uploaded to private Azure evidence storage then reread in
full to verify SHA-256 and length. Its SHA-256 is
`37447bb6aa6f0c34f998133d834d6123f2e5cd29edb6c61fa94407fcd3bd18ef`.
The manifest links the archive, approved immutable images, bound harness/spec,
independent audits and protected receipts.

Before deployment, **83 local tests**, **two Terraform mock tests**, and all
fourteen sequential CPU-reference jobs on each of two Kind workers passed.
The prior source CI was green. CPU qualification does not validate CUDA or CC.
No new scientific image, model download, Torch workload, MIG, MPS or parallel
GPU job was used in this window.

This development sample uses `block: null` and a separate partition. It supplies
one truncated B1 throughput observation, no seven-method comparison, stable
variance estimate, rare-defect detection power or superiority result. The
[sample protocol](../methodology/sequential-throughput-pilot.md) and reserved
**140-job / 23 h 20 min** campaign budget are unchanged. A shorter comparative
schedule is not justified by this run. Wider sampling requires a reviewed,
versioned evidence-storage plan and a new approved window. No project GPU is
allocated while the user decides.
