# Finite-work throughput pilot v1

The first sequential pilot did not measure every method: its B1 job reached the
predeclared 256 MiB trace limit after 50.39 seconds and the following thirteen
jobs did not start. Those originals and their partial result are preserved.
This new development pilot answers a different, concrete question: how long
does each method take to process a fixed amount of work, including its search,
validation, GPU execution and durable original trace collection?

## Fixed work and sequential execution

Execute two development blocks with the seven existing methods B1, B2, B3, B4,
A_NO_STATE, A_NO_DIVERSITY and A_NO_VALIDITY_GUIDANCE. Each job processes
exactly **100 selected cases**, including cases rejected by the final validator.
The normal stopping criterion is the completed case count. A 120-second limit
per job is a safety deadline checked between complete cases, not the intended
job duration or a strict wall-time cutoff. A case already in progress can finish
after this boundary. A job that stops at the safety deadline is incomplete and
must not be represented as a completed measurement. Its original records remain
part of the pilot result.

A selected case is one result of `Search.next()`. B1 and B2 draw one internal
candidate per selected case; the other policies draw sixteen candidates before
selection. Candidate draws are reported separately. Fixing the number of
selected cases therefore measures the cost of each complete policy, including
its candidate pool; it does not equalize internal search effort. Invalid cases
count toward the fixed work and are reported separately from passing cases.
The final safety validator remains in place before any device operation.

Use schedule seed **9100902**, two independently seeded development blocks,
and a randomized method order in each block. Keep the reserved evaluation
schedule and its seeds unchanged. The immutable specification records all
fourteen jobs, their exact seeds and order, fixed work, safety limits, image
digest, source commit, wrapper hash and oracle version. No job overlaps another:
one process uses one qualified native executor, and jobs run successively. Do
not enable MIG, MPS, additional GPU workers or simultaneous GPU jobs.

## Original evidence and resource limits

Retain each original scenario, observations, verdict and trace without sampling,
truncating arrays or replacing full values with hashes. Record rejected cases
and any FAIL, UNSUPPORTED or infrastructure failure. A FAIL is a candidate for
separate reproduction and review, not an automatically confirmed defect.
Stop later jobs after a candidate failure, unsupported operation, infrastructure
failure or resource limit, and publish an explicitly partial result.

The new limits are **1 GiB of original case traces per job**, **8 GiB for the
whole sample**, and a **2 GiB free-space reserve**. A trace-limit crossing may
retain at most one additional complete original record; the record is never
cut in the middle. These limits are declared before GPU execution. They are
not increased after observing an unfavorable GPU result. Local deterministic
generation and size projection must check the actual schedule before deployment,
including the largest supported buffers, stateful rounds, double buffering and
the sixteen-candidate selection policies. CPU size projections validate storage
planning only; they do not measure H100 throughput or validate CUDA behavior.

The host driver, kernel and confidential-computing mode remain pinned. Host
attestation checks, the CUDA references and all 96 IR qualification cases must
pass before the finite-work sample starts. The sample mounts the small wrapper
and specification into the already qualified immutable IR image. It does not
download the model or execute inference jobs.

## Measurement and duration estimates

For every job, report total wall duration (`actual_job_seconds`), completed
selected cases, passing cases, rejected cases, internal candidate draws,
structural and temporal coverage,
and original trace bytes. Wall duration includes candidate generation and
selection, validation, native IPC, device operations, serialization, flushes,
checkpoints and final manifest creation. Also report executor initialization,
close time and gaps between jobs. Keep monotonic timings and UTC start/end
timestamps so that an independent reviewer can verify ordering and durations.

For each method, publish both observed block durations and their range. If both
jobs complete 100 cases, provide conditional projections for **100, 1,000 and
10,000 selected cases per job**:

`projected_job_seconds(N) = observed_job_seconds(100) * N / 100`

These are throughput projections, not guarantees. Initialization, fixed costs,
coverage saturation, adaptive search behavior, payload mix and trace storage
can make longer runs differ. Two observed blocks give an observed range, not
a confidence interval. For a proposed matrix of twenty blocks and seven methods,
sum twenty times each method's projected duration. Report that finite-work
scenario separately from the existing 600-second-per-job draft; do not change
the reserved comparison automatically.

The pilot cannot determine how many cases establish a meaningful scientific
result by timing alone. Report coverage and its progress, but do not equate
coverage keys with distinct defects or claim that coverage saturation proves
adequate defect-detection power. The final scientific sample size, experimental
units, effect of practical interest, precision or power justification and
stopping rules still require a frozen comparison protocol. No favorable
p-value, outcome or coverage threshold retroactively chooses this pilot's work.

## Total cycle and shutdown

Report the full elapsed time from cloud execution start to confirmed H100
deallocation, retaining the VM and its disk until the user's decision. Break out
provisioning, qualification, the fourteen fixed-work jobs, export and release.
Report local preparation, independent review, verified Azure backup and
publication durations separately, including any limits on available timestamps.
Do not present only kernel time or the sum of campaign deadlines as total time.

The costed window binds a saved infrastructure plan and immutable workload
hashes before execution. An independent Azure expiry mechanism deallocates the
VM at the approved deadline. After collecting and verifying the originals,
deallocate the H100 immediately; perform the independent semantic audit and
long-term backup locally with the H100 off. Retain the window's VM, disk and
restart resources until the user's decision; deletion requires a later explicit
user instruction. Preserve the permanent Azure model and
evidence store and unrelated resources. Invoice amounts remain unknown until
Azure publishes actual subscription billing data; retail calculations are
forecasts, not an observed cost.

Publish every complete and partial pilot outcome separately from confirmatory
E4/E5 results. The prior partial sample is retained with its own protocol and
limits. This finite-work pilot does not establish a shorter scientifically
adequate comparison budget, superiority between methods, full E0–E8 completion,
or an automatic authorization for later GPU windows.
