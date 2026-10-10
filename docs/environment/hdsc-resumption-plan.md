# HDSC correction — retained-H100 resumption plan

This plan supersedes the preparation assumptions of the original 90-minute
window. The interrupted attempt and its raw classifications remain preserved:
[incident/result](hdsc-interrupted-window.md). Its 289.713887-second VM interval
is already over. The user has authorized the next start **conditionally on
successful local qualification**; this document alone does not start the VM.

## One reduced window

Maximum planned interval from start request to confirmed deallocation:
**30 minutes**. Forecast incremental budget: **USD 4**. The previously verified
Linux East US 2 rate is USD 6.98/hour: USD 3.49 compute at 30 minutes, with USD 0.51
margin. Confirm the current retail meter in private provenance before execution.
This is not a hard invoice cap; retained disk/IP charges and tax are outside it.
Azure control-plane delays can exceed a requested deadline. The controller and
independent expiry both request deallocation, and release must be confirmed.

The shared clock includes boot, previous-evidence recovery, image/model transfer,
jobs and collection. Guest absolute expiry is minute 23, with a two-minute
admission reserve; independent Azure expiry is minute 27. Planning assumption:
10–25 minutes, **not a measured total-duration forecast**. The small interrupted
RQ2 sample does not measure native dynamic or Transformer execution time.
Any technical error immediately deallocates; diagnosis happens locally. No retry
or second allocation is authorized by this single-window receipt.

## Scientific inventory and handling of the failed attempt

No new seeds, detector thresholds, metrics, workloads or schedule order.
`experiments/hdsc-schedule-v1.json` remains byte-for-byte unchanged. The schedule
has 1,153 records, but the expected execution is:

| Work | Actual jobs / requests |
|---|---:|
| Healthy development capability checks, one per sanitizer | 3 / 3 |
| RQ2 direct CUDA, output-only and CC-Contract | 240 / 240 |
| RQ3 native dynamic | 50 / 50 |
| Transformer healthy/injected pairs | 40 / 80 |
| Separate healthy native/Transformer controls | 80 / 80 |
| ON/OFF performance | 20 / 260 |
| **Executed total** | **433 / 713** |
| Sanitizer-dependent reserved records, explicitly UNSUPPORTED/not executed | **720 / 0** |

There are also 70 model constructions: 630 eager setup forwards and 210 graph
captures. Only one GPU job at a time. Racecheck, RQ1 repeats, Qwen repeats and
Random/B3/B4 search have zero new launches.

The three capability diagnostics must again explicitly reject the unchanged CC
configuration. A healthy alert, incomplete observation or changed capability
stops the window; the reduced plan does not silently grow to 720 tool launches.
Sanitizer's environment rejection is neither a detection nor a missed fault.
RQ2 can compare CUDA status/output-only with CC-Contract, but cannot establish
superiority over an instrumented sanitizer on this confidential configuration.

The interrupted attempt is excluded as a whole from the replacement matrix,
including its valid direct-CUDA subset. This avoids selectively pooling rows
around the failed capability gate. At least 49 reserved RQ2 rows were exposed;
the complete prior count is determined after recovery. The replacement reuses
the unchanged planned inputs, so it must **not** be described as fully unseen
holdout evaluation. The detector and workloads were not tuned on those outcomes.
No old run counts as a new independent block. The historical 50-run RQ1 pilot
and 140-job campaign remain untouched and statistically separate.

## Automated recovery and retained-host protections

Before new GPU workloads, the controller sends the frozen `hdsc-recovery.py`
through verified SSH. It performs only Docker inventory and file reads:

1. Refuse any already-running GPU/HDSC container. Never stop/delete a foreign
   workload or alter the host to make the check pass.
2. Read the old `hdsc-eval-1010a` evidence and control files, rejecting symlinks,
   non-regular files and evidence beyond 2 GiB / 10,000 original files.
3. Stream a hash-indexed archive locally without rewriting old originals.
4. Verify every archived byte, the original plan SHA and the 52-row snapshot
   prefix already privately backed up. Any mismatch stops/deallocates.

Stopped old containers and evidence are retained. New containers use unique
window-specific names, so they cannot collide with leftovers. Cleanup targets
only the current window's containers. On completion, new evidence is collected
with hashes; the VM is immediately deallocated before CPU analysis and private
Azure backup. On error, partial new originals remain on the retained disk.

VM/disk UUIDs, seven ARM resources, driver 595.91.07, kernel
6.8.0-1066-azure-fde, CC ON/PRODUCTION and Secure Boot must match. Create zero,
destroy zero; no driver/system image change, MIG, GPU reset or AKS. Existing
managed-identity expiry guard is renewed/read back before the start request.

## Qualification and authorization gates

The corrected application images were already tested on local Kind and published
by immutable digest in `results/manifests/hdsc-correction-local-qualification.json`.
Only host/controller/recovery scripts change for this window; application/CUDA
sources stay identical to that qualification. Additional CPU tests cover archive
tampering, old-evidence identity, running-container refusal, skip admission,
reduced budget approval and cleanup. CPU tests establish no new CUDA result.

Before start: full local checks, exact-source CI, publication, secret scan, model
hash verification, private evidence backup, frozen executable plan SHA and a fresh
read-only Azure inventory. The receipt records the user's new conditional start
instruction and its qualification fulfillment; it never reuses the completed
window's approval. No run is allowed with changed frozen sources or an already
used execution-attempt directory. All local failure diagnoses precede allocation.

The final report retains incomplete/unsupported/invalid outcomes and paired
block-level uncertainty. Neither completion nor scientific superiority is assumed.
