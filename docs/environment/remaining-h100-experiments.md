# Remaining H100 work after the fixed-work campaign

The current 140-job v0.3 campaign addresses bounded integer E4/E5 evaluation.
Independent raw-case review and final publication are in progress with the H100
deallocated. Its current request-to-deallocation interval was 56 min 20 s;
including the earlier failed zero-work startup, 59 min 19 s. No further H100
allocation is needed to audit and publish that completed execution.

| Experiment | Existing evidence | Remaining work | Further H100 required? |
|---|---|---|---|
| E0 infrastructure/attestation | Real CC host; retained-VM restart; independent CPU MAA/CUDA/IR review; verified deallocation | Independent GPU quote/remote-token authentication, actual allocated-VM expiry shutdown, full Azure kubeadm integration/recreation | Some lifecycle/integration checks require a separately planned GPU window; review existing proofs locally first |
| E1 numerical oracle | Bounded exact integers; real bounded float32 reference pilot | Broader float-oracle calibration, independent variability, oracle freeze | Further real numerical observations after local qualification |
| E2 bounded contracts | 96 real T01–T08 cases and reserved campaign execution | Finish current raw-case audit; any claims beyond this bounded generator need another protocol | No further run merely to review the current bounded corpus |
| E3 historical H08/H09 | Documented reports, causes unconfirmed | Original traces, exact vLLM/model/input/sampling versions and locally qualified isolated reproducer | Blocked by missing prerequisites; no justified run yet |
| E4/E5 policy comparison | 140 successive GPU jobs with 100 selected cases each | Finish independent raw review; adequacy/power and broader claims remain outside v0.3 | No further run to complete the current declared matrix; any extension requires its own plan |
| E6 anomaly reduction | CPU reduction algorithms qualified | Suitable reproduced real anomaly and paired reduction evaluation | Conditional; controlled CPU mutants cannot substitute |
| E7 PyTorch/Qwen | 18 real float components, 24 paired Qwen prompts, 144 paired steps audited | Frozen evaluation with independent repetitions; paired agreement does not prove absolute model correctness | Yes for an expanded real inference evaluation |
| E8 intervention | CPU callable harness qualified | Characterized real anomaly, qualified intervention and paired timings | Conditional; no substitute diagnostic timings |

No total additional H100 duration has been measured for these remaining scopes.
The 140-job timing cannot be reused as a duration for inference, anomaly reduction,
attestation or cloud recreation. Prepare and qualify each remaining component
locally, freeze its workload and costed plan, then obtain approval for the next
GPU window. Measure an appropriate finite workload when timing is unknown.
Preserve the qualified driver/kernel and CC; do not enable MIG, downgrade the
driver, reset the GPU, run overlapping GPU jobs or automatically destroy the
retained VM/disk. Stop and resolve failures locally before any approved resume.

See [current execution proof](../../results/manifests/fixed-work-campaign-execution.json),
[experiment status](../../experiments/status.json) and
[historical prerequisites](../../experiments/historical-cases.json).
