# HDSC approved attempt — stopped on disabled instrumentation

On 2026-10-10 the owner approved the frozen plan
`9cbdc48695ecc666f66b9cc26aa5f08948c7bfb25b94cc0c6a0f631d94710ec5`
(1,153 sequential jobs, up to 90 minutes, forecast USD 12).
The attempt did not complete. The retained VM is **deallocated**; its disk and
restart resources remain intact. No restart is authorized by this completed window.
The [machine-readable receipt](../../results/manifests/hdsc-interrupted-window.json)
supersedes the preparation-only status of the immutable historical plan.

## What happened

Host checks passed for the preserved driver/kernel, CC ON/PRODUCTION and Secure
Boot. All three healthy development controls produced real CUDA output but also
this Compute Sanitizer diagnostic:

```text
Error: Confidential compute mode detected. compute-sanitizer will be disabled.
```

The tool exited 86 and printed `ERROR SUMMARY: 1 error`. The frozen parser lacked
this exact rejection wording and incorrectly labelled it `ALERT`; the healthy
capability gate also accepted that label. Reserved RQ2 jobs consequently started.
This is an implementation error in the harness, not a demonstrated sanitizer
detection, false positive, or CUDA workload error (INC-0122).

Inspection of original output exposed the problem. The operator immediately
requested deallocation, without attempting a driver, CC-mode or host change.
No evidence is counted as a valid instrumented sanitizer comparison. This observed
incompatibility applies to the tested tool version and qualified configuration;
it does not establish universal incompatibility across all future versions.

## Duration and evidence

| Event | UTC |
|---|---|
| Start request | 2026-10-10 19:22:01.347966 |
| Operator stop request | 2026-10-10 19:25:32.428176 |
| Deallocation confirmed | 2026-10-10 19:26:51.061853 |

The conservative start-to-confirmation duration is **289.713887 seconds
(4 min 50 s)**. This measures the complete VM window, not exact billing boundaries.
The deallocation request succeeded. An operator interrupt subsequently interrupted
the controller's cleanup polling; an independent Azure readback confirmed release
and recorded it explicitly (INC-0123).

A monitoring snapshot preserves **52 rows**: three development capability controls
and 49 reserved RQ2 rows. Eleven of those rows use direct CUDA, and 41 launch a
disabled sanitizer (including the three controls). The snapshot predates stopping;
**the final guest job count is unknown locally**. Full originals remain on the
retained disk. An immediate post-stop copy was unavailable because SSH was already
closed. No H100 restart was performed to retrieve them.

An independent CPU audit verified the captured 49 RQ2 consumer witnesses,
generation/payload intent, sums and native detector decisions. This validates only
the captured arithmetic/provenance subset. It neither validates instrumentation nor
completes the reserved experiment. No RQ3, Transformer or overhead result is claimed.

The snapshot is immutable; corrections do not overwrite its original `ALERT`
classifications. Old campaigns and the 50-run pilot remain unchanged. Reserved
inputs were exposed, and this interrupted attempt must be disclosed in future
reports rather than silently pooled with a replacement campaign.

## Local correction and resumption boundary

The correction recognizes the observed diagnostic as `UNSUPPORTED`, treats unknown
instrumentation-disable messages as infrastructure failure, requires the healthy
capability control to pass or explicitly reject the environment, and independently
rejects any disabled-tool `PASS`/`ALERT` in analysis. Regression tests use the observed
diagnostic; they are CPU parser/gate tests, not a claim that instrumentation works.
All 276 local unit tests passed, and an offline regression checked all 41 captured
disabled-tool outputs without modifying originals. The captured archive and hash
index were backed up to private Azure storage and verified by complete remote
GET/SHA-256. SSH keepalives also bound detection of a disconnected guest.

The prior plan and published images remain historical artifacts. The corrected
sources change their hashes and cannot execute under the old plan or approval.
Replacement image qualification, a new frozen plan and fresh owner approval are
required for another window. At the next approved access, recover the complete
interrupted evidence before deciding how to handle the remaining reserved jobs.
Do not rerun unsupported sanitizer jobs or claim they missed semantic faults.
