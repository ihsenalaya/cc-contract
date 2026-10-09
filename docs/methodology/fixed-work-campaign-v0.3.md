# Protocol v0.3 — fixed selected-case E4/E5 evaluation

This version freezes the finite-work design requested by the user: 20 paired
blocks, seven policies, and 100 selected cases per policy per block. It changes
the stopping rule from the preserved v0.2 draft, rather than claiming that a
100-case run completed that draft's 600-second budget. The original
`experiments/comparison-schedule.json` remains immutable. This protocol and the
new execution specification must be hashed before a separately approved GPU
window. Freezing this design does not establish adequate statistical power,
complete E0–E8, or authorize starting the GPU.

## Population, units and schedule

The population is the qualified, bounded T01–T08 integer IR generator with the
`integer_physical_tag_v2` oracle. It excludes arbitrary CUDA programs,
undocumented H08/H09 configurations, model inference and controlled mutants.
E4 comprises B1–B4; E5 comprises A_NO_STATE, A_NO_DIVERSITY and
A_NO_VALIDITY_GUIDANCE, paired with the same B4 run in each block. B3 also
provides the predeclared temporal-guidance ablation. B1 cannot replace the
no-state ablation because its selection policy also differs.

Use the exact block, position, method and seed fields of the original reserved
schedule. Its 20 block seeds and randomized within-block orders were declared
before these GPU outcomes. The development samples used schedule seeds 9100901
and 9100902; their generated block seeds are disjoint. Before execution, verify
that none of the reserved seeds has already been consumed by a GPU evaluation.
Local qualification may exercise these seeds only with an explicit CPU scope;
it cannot enter the GPU evaluation results. Use partition
`fixed_selected_case_evaluation` for the new GPU schedule, and preserve the
original reserved schedule's SHA-256 in the new specification.

One block is the independent statistical unit. The seven policy runs in that
block share its seed; case observations, tokens, replays and candidate draws
are dependent within a run. Execute all 140 jobs sequentially on one shared
qualified executor, following the predeclared order. Do not run overlapping
GPU jobs or choose new seeds after seeing results. Record monotonic and UTC
intervals for each job, including final manifest persistence and original-file
hashing. Record initialization, collection, deallocation and offline review
separately so that job duration is not called total delivery duration.

## Work allocation and safety

The stopping rule is exactly 100 calls returning a selected `Search.next`
scenario per job, including `INVALID_TEST`. These are 14,000 selected cases
over 140 jobs. B1 and B2 draw one proposal per selected case; the other five
policies draw pools of 16. Expected candidate draws are therefore 100 or 1,600
per job, and 164,000 overall. Fixed selected work does not equalize candidate
generation cost, valid CUDA executions, byte traffic or wall time. Report all
these distinctions, including each policy's rejected selected cases.

Preserve the final conservative safety validator for every method, including
A_NO_VALIDITY_GUIDANCE. Invalid selected scenarios consume quota but never
reach CUDA. Selection, generation and feedback follow the pinned image's
existing policy definitions; no outcome-driven metric or policy changes are
permitted. Search feedback includes an executed FAIL as well as a PASS.

Use a 120-second safety guard per job, checked at durable loop boundaries;
it is not a required job duration or a guarantee of a strict 120-second cutoff.
FAIL, UNSUPPORTED, infrastructure failure, resource guards or interruption
stop the sequence and preserve original evidence. Collect and deallocate
before offline analysis. Retain the VM, OS disk and restart resources until
the user decides; no automatic destruction is authorized. Reproductions need
their own authorized plan if they cannot fit the approved window.

Raw trace guards are 1 GiB per job, 32 GiB overall, with a 2 GiB free-space
reserve. One complete case record can exceed the boundary before the runner
stops; preserve that record and report the overshoot. These are operational
guards, not promises that every new seed fits. The observed development sample
produced 628,103,871 raw bytes for 14 jobs. Scaling that observation to 140 jobs
gives 6,281,038,710 bytes (5.85 GiB); a planning allowance of four times that
volume plus 64 KiB per selected case is 26,041,658,840 bytes (24.25 GiB).
Both calculations depend on different, unobserved reserved seeds. Verify the
actual free disk capacity, retain raw byte guards and report a cap-limited run
as partial. Compressed archives, collection staging and temporary files need
capacity beyond the raw trace allowance; compression ratio is not guaranteed.

## Implementation and qualification

GPU execution is pinned to
`ghcr.io/ihsenalaya/cc-contract-ir@sha256:e09597869dab698d082cc56ceb5cbb7c6eb348760e08f617387491837ad1fc8a`,
source commit `1f62b1838196e495d715c1cf063b03ea777aaa94`, with all T01–T08
families supported and no dirty image source. The new mounted orchestration
script and its shared finite-work helper must each be separately hashed; the
image's runner and operation implementation remain pinned. Preserve the
qualified host driver 595.91.07, kernel 6.8.0-1066-azure-fde, confidential
computing production mode and secure boot. Do not enable MIG, change the driver,
reset the GPU or mix implementations.

Before a GPU window, pass CPU unit tests, both Kind workers, hardware-independent
receipt review and mocked lifecycle checks, then obtain approval of a concrete
costed resume plan. Those checks establish orchestration correctness only.
Actual host qualification and the 96-case CUDA IR qualification are required
before evaluation on the resumed GPU. Existing CPU MAA verification supports
specified CPU claims; it does not establish independent GPU remote attestation.
Keep that limitation visible in the eventual comparative result.

## Registered outcomes and defect confirmation

Primary outcomes are the number of externally confirmed distinct defects per
job and detection of any such defect. A raw FAIL is a candidate, never an
automatic confirmed defect. Confirmation requires two separate fresh process
replays with failing original operations, unchanged image/source/oracle and
hashed original replay evidence, followed by explicit external technical
review. Repeats within one process are not two independent reproductions.
The review records its identity, rationale, characterized mechanism and defect
equivalence grouping. Group by the same characterized cause, not by family,
token, payload count or temporal feature. Preserve raw manifests unmodified;
review annotations are separate inputs. Zero confirmed defects supports no
superiority claim and is not proof that no defect exists.

Secondary descriptive outcomes per job are valid selected fraction
(`PASS + FAIL` divided by all selected cases), structural and temporal software
coverage, candidate draws, observations, raw bytes, and whole-job elapsed time.
Coverage measures software features; it does not measure independent defects,
physical bus traffic or absolute hardware correctness. Nondetection time is
right-censored at actual campaign end and remains `null` for time to detection;
never encode a nondetection as zero seconds. Interrupted detections/rejections
remain in explicit partial reports but cannot complete a job's 100-case quota.

## Analysis and limitations

Full GPU summaries and paired comparisons require all 140 declared GPU jobs,
the full 100-case quota for every job, nonoverlapping intervals, all original
hashes verified, a common supported-family set and the exact pinned execution
identity. A legacy `COMPLETE_CASE_LIMIT_LOCAL_ONLY` label may appear in the
image's immutable runner manifests. The new wrapper and independent analyzer
interpret the quota under this versioned protocol and retain the original
label verbatim. Never rewrite it as `COMPLETE_BUDGET`; reaching the safety
guard with fewer than 100 selected cases is incomplete.

Missing, partial, CPU or candidate-stopped jobs are listed separately with
censoring and reasons. Do not silently subset to the favorable complete blocks,
pool development samples, or mix CPU and GPU scopes. If a raw candidate lacks
the registered external review, the defect analysis remains incomplete.
Secondary complete-work summaries may still be shown with that limitation.

For B4 versus B1, B2 and B3, and separately versus each of the three ablations,
report paired block differences for primary and secondary outcomes. Use 95%
percentile paired block bootstrap intervals with 5,000 resamples and seed
59001. Resample whole paired blocks, not case observations. Detection fractions
also receive Wilson intervals; report exact paired McNemar p-values and Holm
adjustment across the three B4 versus B1–B3 primary detection comparisons.
Ablation intervals remain descriptive and are labelled separately. Do not
emit an automatic superiority verdict or use repeated sampling until
significance. The draft useful-effect thresholds (+1 confirmed defect per job,
or +10 percentage points in detection probability) remain unvalidated planning
targets, not achieved claims or a power justification.

The user selected 100 cases per job after a duration pilot. That pilot justified
a timing choice, not scientific adequacy: it observed two development blocks,
not the 20 reserved blocks. Its 140-job proportional projection is 50m37.6 of
whole-job time (descriptive two-block range 46m29.8–54m45.3), excluding resume,
qualification, export, deallocation, review and publication. Neither this range
nor the 32 GiB cap is a confidence bound. The concrete resume window uses the
approved 90-minute, 15 USD envelope and a newly qualified expiry guard; it must
not reuse the old pilot expiry. Local review runs after deallocation and contributes
to total delivery time. No duration for the complete E0–E8 project is established.
