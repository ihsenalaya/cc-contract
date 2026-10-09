# Finite-work H100 development timing sample — 2026-10-09

All fourteen successive 100-selected-case jobs completed and passed independent review. The sample took **5 min 06 s**. The complete cloud cycle through confirmed deallocation took **46 min 08 s**. The VM, its OS disk and network remain present and deallocated until the user decides. No temporary resource was destroyed.

The audit recomputed **1,400 selected cases**, **1,161 PASS**, **239 INVALID_TEST**, **16,400 candidate draws** and **4,069 observations**. No candidate FAIL, unsupported case or infrastructure failure was found. Invalid proposals count toward the selected-case quota and are rejected before CUDA. These are development timing observations; they establish no real defect or statistical superiority.

| Method | Block 0, seconds | Block 1, seconds | PASS / 200 selected | Candidate draws / job | Raw MiB, both jobs |
|---|---:|---:|---:|---:|---:|
| B1 | 2.456 | 2.247 | 167 | 100 | 33.12 |
| B2 | 7.613 | 3.970 | 174 | 100 | 117.83 |
| B3 | 36.442 | 33.053 | 200 | 1600 | 97.29 |
| B4 | 36.545 | 32.831 | 200 | 1600 | 150.88 |
| A_NO_STATE | 9.701 | 9.398 | 200 | 1600 | 25.86 |
| A_NO_DIVERSITY | 36.847 | 30.037 | 200 | 1600 | 97.23 |
| A_NO_VALIDITY_GUIDANCE | 34.661 | 27.952 | 20 | 1600 | 76.80 |

Every job duration includes generation, validation, CUDA execution, evidence serialization/fsync and final hashing/manifest creation. Five methods draw sixteen internal candidates per selected case; B1/B2 draw one. Equal selected-case counts therefore do not imply equal legal-CUDA work or internal candidate counts.

| Target per job for 140 successive E4/E5 jobs | Estimated job time | Range from the two observed blocks | Estimated raw GiB |
|---|---:|---:|---:|
| 100 selected cases | 50 min 38 s | 46 min 30 s–54 min 45 s | 5.85 |
| 1,000 selected cases | 8 h 26 min 16 s | 7 h 44 min 58 s–9 h 07 min 33 s | 58.50 |
| 10,000 selected cases | 84 h 22 min 35 s | 77 h 29 min 38 s–91 h 15 min 32 s | 584.97 |

Formula: twenty jobs per method × the mean of its two full observed job intervals × target / 100, summed across seven methods. These scenarios do not change the reserved 140 × 600-second draft budget (23 h 20 min). That number was an imposed budget, not a measured necessary runtime. Targets above 100 are linear extrapolations. The observed range is not a confidence interval. Scientific sufficiency, practically relevant effects and power/precision planning remain unresolved. E3/E6/E8 depend on characterized anomalies; a total duration for all E0–E8 cannot be derived from this timing pilot.

| Observed phase | Measured time |
|---|---:|
| Terraform apply | 34 min 28 s |
| Full sample | 5 min 06 s |
| Qualification exit to hash-verified original collection | 3 min 59 s |
| Full cloud cycle, before apply to confirmed deallocation | **46 min 08 s** |
| Offline complete finite-work audit, after deallocation | 9 min 23 s |
| Offline host/MAA/CUDA/IR audit, after deallocation | 3 min 07 s |
| Original Azure upload plus complete remote GET verification | 0 min 53 s |

The monotonic controller receipt measures 2767.492104 seconds; UTC subtraction measures 2768.202314, a 0.710210-second clock difference. Both values are preserved. CPU audits and Azure backup overlap and must not be added as consecutive stages. Preparation started before its first recorded timestamp, 19:54:40.262048 UTC; end-to-end preparation timing is a lower bound. Final evidence backup and Git publication are recorded in the separate delivery receipt.

A constant 41-minute cloud allowance would understate a larger workload. Exporting and checking the pilot originals took about four minutes, and larger targets create more traces. The as-executed gzip verifier reread prefixes on backward seeks, so export could scale faster than data volume; a separately qualified one-pass collector is prepared locally after the run. The following full-pipeline figures are explicitly **unverified planning scenarios**, using one comparable creation, the historical unoptimized export proportional to volume, and CPU audit proportional to selected-case count on this PC. They exclude new preparation and publication and may understate export; they are not promised deadlines.

| Target / job | Conditional cloud cycle with scaled export | Conditional offline audit | Conditional sum, before publication |
|---|---:|---:|---:|
| 100 | 2 h 07 min 29 s | 1 h 33 min 50 s | 3 h 41 min 19 s |
| 1,000 | 15 h 40 min 58 s | 15 h 38 min 20 s | 31 h 19 min 18 s |
| 10,000 | 151 h 15 min 45 s | 156 h 23 min 24 s | 307 h 39 min 10 s |

Multiple cloud windows, different provisioning delays, coverage/state growth, storage sizing and CPU audit concurrency require separate planning. None of these projected campaigns is authorized by the completed USD 15 sample window.

Host qualification retained driver 595.91.07, kernel 6.8.0-1066-azure-fde and CC ON/PRODUCTION with SecureBoot. CPU MAA RS256 and the actual applied VM identity were independently verified. Native CUDA 54 observations and IR 96 cases/252 observations passed independent payload/tag recomputation. The sixteen local GPU verifier claims were true; local HMAC receipts, exported GPU quote and NRAS were not independently authenticated. E0 remains partial.

The original 253,406,022-byte archive contains 90 hash-verified files; SHA-256 `7e5cc70393ba70f4851c3d2a71d7e67d2795629d6ebb7dc812270d698e44e4ee`. Raw case traces total 628,103,871 bytes. Originals remain outside Git and were uploaded to private Azure storage, then reread in full for SHA-256 and byte-length verification. All independent receipts are linked by the [result manifest](../../results/manifests/finite-work-sample-gpu-result.json).

ActualCost returned no rows: actual charges are unknown, not zero. USD 15 was a forecast. Azure separates provisioning from power state; this VM was observed Starting and Running while provisioning still said Creating. Thus Creating alone cannot establish free waiting time. Starting/Running are billed; deallocation releases instance compute, while retained disks/network can remain chargeable. [Microsoft billing states](https://learn.microsoft.com/en-us/azure/virtual-machines/states-billing). Cost data is delayed and remains estimated until invoiced. [Microsoft Cost Management data](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/understand-cost-mgt-data).
