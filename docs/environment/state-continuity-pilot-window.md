# State-continuity pilot v0.1 — proposal, not authorization

**STOP: the existing H100 remains deallocated. Fresh explicit user approval is
required. No cloud compute was started, created or modified during preparation.**

## Fault models

| ID | Provenance | Bounded scenario |
|---|---|---|
| L1 | Zhu & Zaidman, ICST 2020, DOI [10.1109/ICST46399.2020.00030](https://doi.org/10.1109/ICST46399.2020.00030), Listing 14; Simulee [§3.2](https://lingming.cs.illinois.edu/publications/icse2020b.pdf) motivates dependencies | Adapt synchronization removal to the wrong host event and a forced consumer-before-late-transfer schedule. `ADAPTED_FROM_PUBLISHED_SYNCHRONIZATION_FAULT`; not the identical MUTGPU operator. |
| L2 | [NVIDIA CUDA Graph documentation, §4.2.3](https://docs.nvidia.com/cuda/archive/13.1.1/cuda-programming-guide/04-special-topics/cuda-graphs.html#updating-instantiated-graphs) | Omit updating a captured pointer from immutable A/g1 to A/g2. `DOCUMENTATION_BACKED_BEHAVIOR`; not an NVIDIA bug. |
| C1 | New CC-Contract proposal | Host produces A/g2; omitted transfer leaves valid device A/g1. |
| C2 | New CC-Contract proposal | Substitute valid, compatible B/g2 when A/g2 is expected. |

The [source audit](../methodology/state-continuity-fault-models-v0.1.md) separates
published claims from our adaptations. The
[protocol](../methodology/state-continuity-pilot-v0.1.md) freezes the fault models,
matrix, oracle, limitations and metrics.

## Verified local result

The table describes one **CPU model** pass; the same matrix also passed on each
of two Kind CPU workers. These repetitions are engineering checks, not additional
independent scientific samples. No successful real CUDA execution is claimed.

| Scenario | Runs | Activated | CUDA-success-like model behavior | Detected | Missed | Oracle receives injection flag? |
|---|---:|---:|---:|---:|---:|---|
| HEALTHY | 10 | 0 | 10 | 0 | 0 | No |
| L1 | 10 | 10 | 10 | 10 | 0 | No |
| L2 | 10 | 10 | 10 | 10 | 0 | No |
| C1 | 10 | 10 | 10 | 10 | 0 | No |
| C2 | 10 | 10 | 10 | 10 | 0 | No |

Healthy false positives: **0/10 in the CPU model**. The independent auditor
recomputed all three sets of 50 raw observations without importing the injector
or detector. Its tampering tests reject altered contracts, observations,
classification, activation and run order. Twenty-five targeted tests pass,
including deallocation after simulated start, host, collection and interrupt
failures. [Source CI passed](https://github.com/ihsenalaya/cc-contract/actions/runs/38068355607).

CUDA 12.8.1 compilation succeeded locally. Both Kind workers verified
`UNSUPPORTED` without a CUDA device. This PC does not expose a NVIDIA management
executable or `libcuda.so.1`; `/dev/dxg` alone is not a usable CUDA GPU.
Kind's service account has no secret-read permission or mounted API token;
the containers run non-root with a read-only root filesystem and dropped
capabilities. The [qualification manifest](../../results/manifests/state-continuity-local-qualification.json)
links the original proof hashes.

Source commit: `ddff8775705a85c278d208b1ba504d18226b7551`.
Locally built, Kind-qualified, published and pulled back by digest:

```text
ghcr.io/ihsenalaya/cc-contract-continuity@sha256:fd60712704b01ca33988aa2734fc0da8cc7c0041eb57669c9237be87df9cc068
```

Host detector time is measured. Total GPU instrumentation overhead is explicitly
unmeasured: a matched uninstrumented workload would be a different experiment.

## Proposed H100 window

| Item | Bound / evidence |
|---|---|
| Exact matrix | 50 successive executions: 10 healthy + 10 each L1/L2/C1/C2 |
| Test time | 10 s timeout per worker; 8 min 20 s cumulative worker allowance; 9 min external harness timeout |
| Total VM time | Planning ceiling 30 min, from start request through deallocation; immediate release on completion or failure |
| Forecast | A 10–20 min VM window is a planning assumption, **not measured H100 timing for these kernels**; CPU timings are not extrapolated |
| Budget | USD 5 forecast ceiling; Linux retail compute USD 6.98/h × 0.5 h = USD 3.49, leaving USD 1.51 reserve |
| VM | Existing `cc-contract-work-sample-1009b`, East US 2, `Standard_NCC40ads_H100_v5` |
| VM identity | `2986ddd2-c122-4884-8f42-d7ad3d0a38ef` |
| Retained OS disk | 128 GiB, unique ID `323889df-fc1f-45ea-a54d-dd47ee8a1f52` |
| Latest review | `2026-10-10T16:38:53.410782+00:00`: `PowerState/deallocated` |
| Resources | Existing VM, disk, network/IP, expiry workflow and permissions; zero creations, replacements or deletions |
| Independent guard | Enabled, every minute, managed identity's read/deallocate permissions verified in Azure |
| Plan SHA-256 | `71030df624b9329b79f9ba6e3a92ce778a8b29825f8d725e57861b5d3ef89df9` |

Retail price was retrieved from the
[Azure Retail Prices API](https://prices.azure.com/api/retail/prices?%24filter=armSkuName%20eq%20%27Standard_NCC40ads_H100_v5%27%20and%20armRegionName%20eq%20%27eastus2%27%20and%20priceType%20eq%20%27Consumption%27).
This is a forecast, not a measured invoice or provider-enforced spending cap.
Azure scheduling/deallocation latency can exceed a nominal deadline. Existing
disk/storage retention charges continue while compute is deallocated and are
not unlimitedly covered by a short-window budget. No automatic budget extension.

## Automation after approval only

`scripts/continuity-window.py review` only reads Azure and writes a private plan.
It has completed successfully; **`run` has not been invoked**. The private plan
is `~/.local/state/cc-contract/continuity-1010a/plan.json`; there is no approval
receipt. A completed or stale authorization is rejected.

After an explicit plan-bound user decision, the controller rereads VM/disk
identity, stopped state and guard. While compute remains off, it renews only the
existing workflow's expiry via the documented
[Logic Apps workflow PUT API](https://learn.microsoft.com/en-us/rest/api/logic/workflows/create-or-update?view=rest-logic-2019-05-01),
and verifies the readback before requesting start. Expiry is armed for 28 minutes
to reserve time for release within the 30-minute planning ceiling. The controller
has at most 8 minutes to establish SSH, invokes the fixed host script, exports
small original records with verified SHA-256, and deallocates in `finally`.
If the local controller disappears, the independent Azure guard remains armed.
The guard update is preserved for subsequent read-only Terraform state refresh;
never apply an older saved Terraform plan that would revert its deadline.

Host qualification requires the preserved NVIDIA 595.91.07 driver,
`6.8.0-1066-azure-fde`, CC ON/PRODUCTION and Secure Boot. No driver changes, MIG,
reset or rebuild. Registry authentication is transient and removed by the host
script. Partial evidence remains on the retained disk if transfer fails.
Heavy audit and any debugging take place on CPU after confirmed deallocation.
Mocked cleanup tests and guard readback do not establish actual timed expiry
against an allocated VM; that broader E0 claim remains unvalidated.

## GO / NO-GO

Local gate passed: observed bytes, not an injection label, determine detection.
The H100 scientific question remains open. Continue beyond the pilot only if
at least two fault models exhibit a wrong consumed state with CUDA success and
correct detection, with no healthy alerts or injected-fault misses and complete
valid evidence. Report nonactivation per fault. Stop expansion on ordinary CUDA
errors alone, circular detection, unobservable state or healthy alerts. There
is no B3/B4 superiority claim, field vulnerability claim or statistically
established low false-positive rate from this small deterministic pilot.

The prior 140 jobs and 14,000 selected cases, E4/E5 results, manifests and original
archives are untouched. They remain the separate bounded no-injected-fault
baseline, including its 2,377 pre-CUDA rejections.

**STOP. Await the owner's new explicit authorization before using H100.**
