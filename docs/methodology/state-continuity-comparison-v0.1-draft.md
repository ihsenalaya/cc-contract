# Possible random / B3 / B4 comparison — unfrozen design

The separate [mechanism pilot](../environment/state-continuity-pilot-result.md)
passed. This document prepares the next scientific question only. No campaign,
new H100 use, sample size, duration or budget is approved here.

The question is whether state-aware generation reaches distinct, activated
state-continuity faults more effectively under a common resource budget.
Replaying the same four already-known failing cases cannot answer it: all
methods would receive the answer directly. A comparison must test search and
generation, keeping the qualified detector identical across methods.

Before freezing a comparison:

1. Define an operation grammar and eligible injection sites independent of the
   generator. Include healthy paths and nonactivating schedules. Define exactly
   what constitutes one distinct fault target, to avoid counting syntactic
   duplicates as discoveries. Keep the deterministic L1 scheduling intervention
   labeled as an adaptation.
2. Separate development and reserved evaluation seeds/targets. Do not tune on
   the 50 mechanism-pilot outcomes and call them an independent evaluation set.
   Freeze target equivalence, handling of invalid candidates and observation
   requirements before measuring comparative performance.
3. Map random, B3 and B4 to this new grammar explicitly. Hold input information,
   detector, eligibility and fault opportunities constant; record the guidance
   information available to each method. Verify their differences on CPU first.
4. Use paired blocks with a balanced randomized serial method order. Treat
   blocks, not packets or repeated copies of one fault, as experimental units.
   Choose a primary budget that genuinely equalizes opportunities or cost,
   and report valid cases, generation draws and real wall time alongside it.
5. Predeclare detection-by-budget and censored time-to-first-distinct-target
   metrics, minimum useful effect, confidence method and multiplicity handling.
   Estimate variance on a separate development workload before choosing an
   evaluation sample size; this deterministic 10-per-fault pilot cannot provide
   a comparative power calculation or total H100 duration.
6. Run local/Kind gates, freeze code and evidence schema, then prepare a new
   costed plan for the retained VM. Only a fresh explicit user approval can
   authorize GPU execution. Retain negative or inconclusive outcomes unchanged.

This preparation adds no superiority claim and leaves historical E4/E5 intact.
