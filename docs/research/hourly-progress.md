# HDSC preparation checkpoints

All times are UTC. Existing GPU results remain unchanged. A checkpoint's source
commit is recorded in the immediately following journal commit, avoiding a
self-referential Git SHA.

## 2026-10-10T18:05:28Z — first published implementation checkpoint

- Commit: `f2f8cdac76e197065c5da00429b4975070985e5f`, pushed by the existing verified synchronizer.
  CI: [38074379549](https://github.com/ihsenalaya/cc-contract/actions/runs/38074379549), success.
  Baseline: `67965582f5ce735e6aea18336ee23fb078ec31a7`.
- Completed: seven-field online model, four-cause benchmark and disjoint splits,
  status/output/sanitizer adapters, dynamic worker, pretrained Transformer and
  ON/OFF harness; ten scientific documents with explicit novelty limitations.
- Evidence: 48 CPU RQ2 runs independently audited (24 detected injections,
  24 healthy without alerts); 47 dynamic sequences; four trained-model fault pairs;
  matching CPU performance paths. These are development results, not GPU results.
- Tests: 263-test previous suite passed; 25 current targeted HDSC tests passed,
  including approval rejection and deallocation on failed start/guest failure.
  Full 270-test suite subsequently passed; 27 current HDSC tests (including two additional reporting checks) passed. Secret scan passed.
- Kind: native image passed on two CPU workers; AI image passed on one CPU worker.
  These development images precede final source freezing and will be rebuilt.
- Blockers: final image/source provenance, current-source CI, final evidence backup,
  frozen final window and independent evaluation reporting preparation.
- Scientific decisions: four causes only; equal-output profiles are constructed;
  Random/B3/B4 deferred; no reserved execution or tuning; no broad LGT4CG novelty claim.
- Next: verify, commit/push, qualify final images, freeze and present a costed plan.
- H100 state: **DEALLOCATED**. No new allocation authorized or performed.

## 2026-10-10T18:10:00.449639+00:00 — lifecycle and reporting checkpoint

- Commit SHA: `37dcb8c9b9a0cc0d6893cde33326f41ac91f3208`; [CI 38074712829](https://github.com/ihsenalaya/cc-contract/actions/runs/38074712829) passed.
- Completed: fail-closed approval, retained-resource lifecycle, offline report with partial-run and invalid-pair handling.
- Tests: 270-test full suite; 27 current targeted tests; release guard; shell syntax and compile checks; Trivy before push.
- Blockers: final Kind image receipts, image publication, archive backup and plan freeze.
- Decision: no reserved outcomes generated; 90-minute/12-USD proposal remains unapproved.
- Next: finish immutable image qualification and freeze the plan.
- H100 state: **DEALLOCATED**.

## 2026-10-10T18:17:09.461593+00:00 — protocol and controller freeze

- Commit SHA: recorded in the following public qualification manifest and journal update.
- Completed: final core and trained-AI Kind checks; identical qualified image configurations will be checked against registry manifests; frozen inventory and costed 90-minute/12-USD plan.
- Tests: 28 current HDSC tests passed, including altered archive-hash rejection; prior full 270-test suite and 272-test checkpoint CI passed. Full frozen-source CI follows push.
- Backups: model and development originals verified by complete Azure GET/SHA-256.
- Blockers: final registry receipt, frozen-source CI and executable plan SHA. No new GPU authorization.
- Decisions: 1,153 scheduled jobs, 1,433 requests plus 840 setup forwards; unsupported sanitizer jobs remain explicit; time estimate unmeasured.
- Next: publish provenance, verify exact plan, STOP for owner decision.
- H100 state: **DEALLOCATED**.
