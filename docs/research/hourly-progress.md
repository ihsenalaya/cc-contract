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

- Commit SHA: `4e3b3a296a97b5a0c1f173c034c6028bbbbefb70`; [CI 38075175310](https://github.com/ihsenalaya/cc-contract/actions/runs/38075175310) passed all 273 tests.
- Completed: final core and trained-AI Kind checks; identical qualified image configurations will be checked against registry manifests; frozen inventory and costed 90-minute/12-USD plan.
- Tests: 28 current HDSC tests passed, including altered archive-hash rejection; prior full 270-test suite and 272-test checkpoint CI passed. Full frozen-source CI follows push.
- Backups: model and development originals verified by complete Azure GET/SHA-256.
- Blockers: final registry receipt, frozen-source CI and executable plan SHA. No new GPU authorization.
- Decisions: 1,153 scheduled jobs, 1,433 requests plus 840 setup forwards; unsupported sanitizer jobs remain explicit; time estimate unmeasured.
- Next: publish provenance, verify exact plan, STOP for owner decision.
- H100 state: **DEALLOCATED**.

## 2026-10-10T18:27:40.246907+00:00 — ready for owner review; STOP

- Frozen source commit: `4e3b3a296a97b5a0c1f173c034c6028bbbbefb70`; image source `f2f8cdac76e197065c5da00429b4975070985e5f` has identical application/CUDA sources.
- Completed: 273-test green source CI; native Kind checks on two workers; trained-AI Kind checks on one; both immutable images published and registry config digests matched to Kind receipts; full remote verification of model, development and final-local evidence.
- Plan: `results/manifests/hdsc-final-h100-plan.json`; SHA-256 `9cbdc48695ecc666f66b9cc26aa5f08948c7bfb25b94cc0c6a0f631d94710ec5`. Inventory: 1,153 jobs, 1,433 requests, 840 additional setup forwards. Proposed ceiling: 90 minutes, 12 USD incremental budget; completion time remains unmeasured.
- Incidents: INC-0120 preserves driverless sanitizer launch failure (INFRA_FAILURE, not a clean GPU result); strace confirms target argument forwarding and missing libcuda before SIGSEGV. Exact internal crash mechanism unconfirmed. INC-0121 records reuse of an existing registry layer instead of redundant PC upload.
- Scientific decisions: no reserved outcomes read, no thresholds tuned, no historical evidence changed. LGT4CG novelty remains provisional. Racecheck has no launches; Random/B3/B4 search deferred.
- Remaining hardware uncertainty: sanitizer/CC capability, dynamic CUDA and real application overhead require the proposed approved window. The three capability gates precede reserved testing; unexplained failure stops the VM.
- Next task: **STOP. Await fresh explicit owner approval of this exact plan.** No approval receipt or execution-attempt file exists for this window.
- H100 state: **DEALLOCATED**; retained VM/disk and guard verified read-only.

## 2026-10-10T19:28:08.488706+00:00 — approved window stopped; retained VM deallocated

- Owner explicitly approved the frozen 90-minute / 12-USD plan. Start: `2026-10-10T19:22:01.347966+00:00`; deallocated confirmed: `2026-10-10T19:26:51.061853+00:00`; conservative total: 289.713887 seconds.
- INC-0122: Compute Sanitizer explicitly disabled itself under CC ON; parser misclassified its environment diagnostic as an alert. The healthy capability gate did not reject that alert. Operator immediately requested deallocation when raw output was inspected.
- Snapshot contains 52 recorded jobs (3 capability + 49 reserved RQ2); final guest count is not known locally. Full originals remain on the retained disk. No sanitizer comparison or completed campaign is accepted. No thresholds or workloads tuned.
- Original snapshot and a separate native-byte audit are preserved privately; public receipt: `results/manifests/hdsc-interrupted-window.json`. This audit does not validate sanitizer instrumentation.
- Corrections: exact diagnostic recognition, fail-closed unknown disable messages, healthy-control gate, independent report rejection, bounded SSH connection-loss detection. All 276 local unit tests passed; all 41 captured disabled-tool outputs are correctly rejected by the independent audit and classified unsupported by the corrected parser. Secret scan passed. Captured originals were backed up with full remote GET/SHA-256 verification. Replacement images are not yet requalified.
- Prior results and frozen plan remain immutable historical evidence. Reserved inputs have now been exposed; future work must explicitly disclose this interrupted attempt.
- H100: **DEALLOCATED**, VM and disk retained, zero deletions. No new restart approved.
