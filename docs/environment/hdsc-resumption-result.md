# HDSC resumption: native results audited, AI incomplete

Window `hdsc-eval-1010b` ran under the owner's conditional authorization, after
local qualification and exact-source CI passed 282 tests. The frozen plan was
`28e07560b63ecd77b86d6953413ce64d989eaee679e9e21efc31f6d601f59ff2`,
limited to 30 minutes with a USD 4 forecast. The
[machine-readable result](../../results/manifests/hdsc-resumption-gpu-result.json)
links original archive hashes, independent analysis and verified private backups.

## Completion and VM duration

| Work | Verified outcome |
|---|---|
| Healthy development capability controls | 3 executed; each explicitly rejected by Compute Sanitizer under CC |
| RQ2 direct CUDA | 240 completed and audited |
| RQ3 native dynamic | 50 completed and audited |
| Additional native healthy controls | 70 completed and audited |
| Sanitizer-dependent records | 720 UNSUPPORTED, not executed |
| Transformer fault pairs | 40 without locally verified completion |
| Transformer healthy controls | 10 without locally verified completion |
| ON/OFF performance jobs | 20 without locally verified completion |

There are **363 completed actual native jobs**, not 1,083 executed jobs:
the latter is the count of native schedule records including unsupported skips.
All 70 AI jobs remain unvalidated; final attempted/completed guest counts are
unknown until their logs are recovered. No AI outcome is inferred from CPU tests.

Start requested: **2026-10-10 20:12:08.361080 UTC**.
Deallocation confirmed: **2026-10-10 20:25:20.032750 UTC**.
Total **791.671670 seconds (13 min 12 s)** includes startup, recovery, image pulls,
native experiments, attempted AI execution and deallocation. The native runner
itself took 347.799001 seconds. This is a conservative VM-window measurement,
not a statement about exact billing boundaries or an Azure invoice.

The controller stopped on guest exit 1 and confirmed deallocation; a separate
Azure readback agreed. VM and disk are retained, zero resources deleted.
The earlier interrupted window cost 289.713887 seconds of measured VM-window
time, separately: the two HDSC attempts total 1,081.385557 seconds (18 min 1 s).
Earlier historical campaigns are outside that total. No restart is authorized
by either completed window.

## Bounded scientific findings

RQ2 contains 120 healthy/injected target pairs in ten paired blocks. All 120
injections activated and returned CUDA success. CC-Contract detected 120/120;
the 120 healthy partners passed. Output-only checking detected the 40
changed-output cases and missed the 80 equal-payload/sum-collision cases.
The native byte audit recomputed intent, consumed witnesses and arithmetic.

Per profile, the CC-Contract detection advantage over CUDA status is 100 percentage
points (paired-block bootstrap 95% interval [100, 100]). Against output-only it is
0 [0, 0] points for changed output, and 100 [100, 100] points for each of the other
profiles. Degenerate intervals describe these uniform controlled blocks; they do
not establish universal detection. Relative improvement over zero is undefined.
Each profile contains four causes per block, rather than independent packets.

Native dynamic execution contains 40 injected runs (ten per fault cause) and ten
healthy runs. Each injection produced one continuity alert; healthy runs produced
none. The paired-block alert-fraction difference is 100 points [100, 100]. The
70 separate native healthy controls also produced zero alerts. These bounded
samples do not establish a general zero false-positive rate.

All three sanitizer controls emitted the explicit confidential-computing rejection.
The independent auditor verified the original diagnostics before accepting the
720 skips. **No instrumented sanitizer detection or missed detection is claimed.**
RQ2 is therefore answered only for CUDA-status and output-only baselines on this
configuration. Racecheck and secondary search comparisons were not launched.

## AI failure and evidence limits

The last preserved live observation, at 20:23:07 UTC, showed a successful AI-image
pull at its approved digest and empty AI stdout/stderr at that instant. At
20:23:58.532603 UTC the guest returned exit 1. The final error was redirected to a
guest file and was not forwarded over SSH before automatic deallocation. Its
precise cause remains **unconfirmed**: image-download timeout, model, PyTorch or
CUDA-Graph failures must not be asserted without the final log (INC-0128).

Core originals were checkpointed, verified and privately backed up before AI
execution. Their independent audit was performed locally after deallocation.
Final AI originals remain on the retained VM disk. A local host-script correction
now forwards bounded diagnostic tails over the existing SSH connection on failure,
preserving the original exit status even if cleanup fails. This improves future
diagnosis; it does not fix an as-yet-unidentified AI execution error.

The next dependency is read-only recovery of those final logs, followed by local
diagnosis. No new H100 allocation or disk attachment is performed for that purpose
without an approved concrete plan. Do not rerun completed native experiments just
to obtain AI results. AI completion still needs its 40 fault pairs, ten separate
healthy runs and 20 performance-mode jobs, original audits and ten paired-block
overhead estimates. No end-to-end overhead is available yet.

## Prior evidence and interpretation

The complete recorded prior archive was recovered before the new workloads:
**75 recorded jobs**, comprising three controls and 72 RQ2 rows. Of these, 17 used
direct CUDA and 58 launched disabled sanitizer tools. Its original 52-row captured
prefix and prior plan hash matched. These are complete recorded rows, not a count
of every attempted or in-flight operation. No prior original was changed, and the
entire prior attempt is excluded from this result. No detector threshold, seed,
workload or schedule order was changed to improve observed outcomes.

The replacement inputs have been exposed previously and are not fully unseen
holdout data. They are seeded variants of four controlled causes, not 120 newly
discovered bugs. RQ2's device projection covers three fields; seven-field dynamic
relations rely in part on a trusted host adapter. No malicious-adapter, independently
attested semantic-state, absolute model-correctness or Q1 novelty guarantee follows.
The 50-run RQ1 pilot and historical 140-job campaign remain unchanged and separate.
