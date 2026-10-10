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

## 2026-10-10T19:40:11.402556+00:00 — correction qualified and published; H100 stays off

- Corrected source: `a33714f68b3764bff30a008e86cda8114d8e1bc2`; [CI 38080136525](https://github.com/ihsenalaya/cc-contract/actions/runs/38080136525) passed all 276 tests.
- Core image passed on two Kind CPU workers; Transformer image passed on one. Both also passed the exact observed diagnostic regression in their built containers. Image publication followed successful local qualification and source CI.
- Registry manifest and configuration hashes match every Kind receipt: core `ghcr.io/ihsenalaya/cc-contract-hdsc@sha256:6598ec487e92e40ac43c5a89c7c5c0f9d4cfa3c699739fa98a3136d6dd92164d`; AI `ghcr.io/ihsenalaya/cc-contract-hdsc-ai@sha256:55ee511446f8600f319ee09643c5cfa5d487b0397aab7949332f04c369ab778d`.
- Qualification originals, CI logs and final retained inventory are backed up privately, verified by full remote GET/SHA-256. Receipt: `results/manifests/hdsc-correction-local-qualification.json`.
- The independent final readback confirms the same VM/disk identities, seven retained ARM resources and **DEALLOCATED**. No further GPU run or restart.
- Remaining: prepare a fresh resumption plan with interrupted-evidence recovery and retained-container preflight; obtain fresh approval. Unsupported sanitizer jobs cannot support a detection comparison. No new executable plan or authorization has been created.

## 2026-10-10T20:05:48.969440+00:00 — local resumption work continued under conditional authorization

- User instruction: “une foie tout fonctionne en local commence avec la h100”. This is fresh conditional permission for the next window, not reuse of the previous receipt. Announced reduced limits: 30 minutes / USD 4; single GPU job at a time.
- Completed: read-only old-evidence recovery with archive and prefix checks; refusal of active GPU/HDSC containers; unique current-window container names; reduced deadline binding; independent verification of unsupported-job admission.
- 37 targeted tests passed, including archive preservation, altered previous-plan/prefix rejection and proof that skipped reserved jobs never call the worker. The full 281-test local suite passed, followed by all 37 final targeted tests including the added admission-proof regression (282 tests expected in final CI). Final exact-source CI precedes any start.
- Application/CUDA sources and immutable images remain identical to the already Kind-qualified correction; original schedules, seeds and old results remain unchanged. No new image import is required.
- Retail price rechecked: exact Linux on-demand East US 2 meter USD 6.98/hour; maximum 30-minute compute USD 3.49, proposed total USD 4.
- H100 remains DEALLOCATED during all local work. Future executable plan/receipt bind recovery, 433 expected executed jobs and 720 explicit unsupported records; the interrupted attempt is excluded rather than pooled.

## 2026-10-10T20:11:09.101461+00:00 — local qualification fulfilled; reduced plan frozen

- Exact source `df88b4cf8a67d1c51751a9131b465b7b2e72156f`: [CI 38082539946](https://github.com/ihsenalaya/cc-contract/actions/runs/38082539946), 282 tests passed. Source/application identity and model hashes verified; local proof archive verified by full Azure GET.
- Read-only Azure review confirms retained VM DEALLOCATED, matching VM/disk identities, seven ARM resources and valid independent guard. No mutations during review.
- Executable plan SHA-256: `28e07560b63ecd77b86d6953413ce64d989eaee679e9e21efc31f6d601f59ff2`; 30-minute / USD 4 window, 433 expected executed jobs, 720 unsupported records without execution. Old evidence is recovered and verified first; no pooling.
- The user's fresh conditional instruction is now fulfilled and recorded in a private plan-bound receipt. This is not a reuse of the completed-window approval. Publication precedes the authorized start; no additional permission request is needed.

## 2026-10-10T20:29:57.131931+00:00 — native GPU results audited; AI failure and recovery preparation

- Executed source: `df88b4cf8a67d1c51751a9131b465b7b2e72156f` (282-test source CI passed); prestart publication `e7c32176cd6c83a322def2e62309c25cbcbba392`. New changes are recorded in this checkpoint commit.
- H100 window `hdsc-eval-1010b`: 363 native jobs completed, 720 unsupported records not executed. Independent CPU audit passed; core originals and analysis backed up with full Azure GET verification.
- RQ2: 120/120 injected detections, 0/120 paired healthy alerts; output-only misses the 80 unchanged-output cases. RQ3 native: 40/40 injected alerts, 0/10 healthy; 0/70 additional native healthy alerts. Ten paired blocks, controlled variants only. No sanitizer superiority claim.
- Prior archive recovered: 75 complete recorded jobs (72 reserved); entire attempt excluded. Original 52-row prefix verified. No frozen workload, seed or scientific metric changes; old RQ1/campaign results unchanged.
- INC-0128: AI guest exit 1, cause unconfirmed until final log recovery. Image download succeeded. Native checkpoint preserved independently. Final AI counts unknown; 70 AI jobs unvalidated, no RQ4 result.
- VM start-to-confirmed-deallocation: 791.671670 seconds (13 min 12 s). VM/disk retained, zero deletion. H100: **DEALLOCATED**.
- Local host correction forwards bounded error tails before automatic release without retry; original status survives cleanup errors. Next: user-authorized recovery-only window, zero experiments, 10-minute planned ceiling / USD 2 forecast, then immediate release and local diagnosis.
- Validation: full local 283-test suite passed, followed by the final 41 targeted HDSC tests including three new recovery-only regressions (286 total tests expected in source CI). Shell syntax, compilation and public result-count checks passed. Frozen recovery plan SHA: `c80fa3037c06ce0933131d7e33e383b5e271cdb927f0b1ae26a2c027bde65fad`.

## 2026-10-10T20:47:22.453345+00:00 — recovery complete; graph correction under local qualification

- Published checkpoint `815212b1f53be0d8b5f0da7d4f98d5eec22757b8`; source CI [38084163134](https://github.com/ihsenalaya/cc-contract/actions/runs/38084163134) passed 286 tests.
- Authorized recovery-only H100 window: start 20:34:56.779375 UTC, confirmed DEALLOCATED 20:37:46.337381 UTC, total 169.558006 seconds. Zero experiments/deletions; original archive and core identity verified and backed up.
- INC-0132: first Transformer construction failed on a scalar mask tensor allocation during CUDA Graph capture; zero AI jobs completed. Native results remain valid.
- Correction preallocates the same scalar, pins original source identity, preserves attention arithmetic/weights and applies equally to ON/OFF. Four trained-model CPU development prompts × three buffers have exact original/adapted logits. No GPU validation claim.
- Fresh owner instruction authorizes H100 after complete local qualification, with no weakened experiments. Announced next scope: two development controls plus 70 AI jobs, 30-minute planned maximum / USD 4 forecast, stop on any technical error. The prior recovery authorization is not reused.
- H100: **DEALLOCATED**. Next: qualified local AI image, exact-source CI, frozen executable AI-only plan, then the conditionally authorized window.

## 2026-10-10T20:55:37.438608+00:00 — AI correction qualified; conditional authorization fulfilled

- Frozen executable source `7a90394807436945c419fd0271410ddecd413844`; [CI 38085197644](https://github.com/ihsenalaya/cc-contract/actions/runs/38085197644) passed 288 tests. Full local suite passed 288 tests; three additional actual PyTorch image tests passed (Torch-dependent class skipped in source CI).
- Trained CPU model: exact upstream/adapted logits on four development prompts and three buffers each. CPU ON/OFF performance harness tokens match. Kind actual image passed four fault pairs and trained-model equivalence; namespace cleaned up.
- AI image published as `ghcr.io/ihsenalaya/cc-contract-hdsc-ai@sha256:a77efb0fe7a0422f5c32e361d7cd7a62a04eda295f8c0ec0b45b9e8c11be9b3a`; registry index/platform bytes and Kind config digest verified. All local evidence privately backed up with full remote GET.
- Executable plan SHA `fc992fd61490766db9a7c5abd516f715dc8f5726468f397df6b1314f0bed887b`: only AI, two development gates + 70 jobs, 30 minutes / USD 4 forecast. Completed native jobs are not repeated. The owner’s newest conditional start instruction is recorded separately; the recovery-only permission is not reused.
- Inventory confirms retained VM/disk identities and DEALLOCATED before execution. H100 graph correction remains unvalidated until the two actual development checks pass. Any discrepancy stops before reserved AI admission. Negative experimental outcomes remain reportable.

## 2026-10-10T21:08:45.946288+00:00 — supported HDSC matrix complete; H100 released and audit verified

- Frozen executable source `7a90394807436945c419fd0271410ddecd413844`, prestart commit `8f480610bfa3c0684fca1852c2beca539a533260`; source CI passed 288 tests and three actual PyTorch image tests passed separately. Local and Kind gates preceded the authorized start.
- Window `hdsc-ai-1010d`: two exact original/adapted/CUDA-Graph development controls passed, followed by all 70 sequential AI jobs. Zero technical failures or retries. No native/RQ1/140-job reruns.
- Start 20:56:28.019552 UTC; confirmed DEALLOCATED 21:03:30.503676 UTC: **422.484124 seconds (7 min 02 s)** including collection and release. Read-only final inventory at 21:06:41 UTC independently confirmed retained VM/disk identity, seven resources and no deletions.
- Offline independent audit: 1,153 accounted schedule records = 433 executed jobs + 720 unsupported/not-executed rows; two additional development controls independently verified. Native and AI section provenance remains distinct.
- AI: 40/40 injected detections with changed tokens, 0/40 paired healthy alerts, 0/10 additional healthy alerts. Full separate healthy corpus: 0/80 alerts. Performance: ten valid pairs, 200 measured requests, no token disagreements; mean p50 difference +0.567142 ms, 95% paired-block interval [0.466787, 0.680340] ms. Mean per-block relative change +2.155984%; ratio of means +2.103406%.
- Memory estimate retained even though negative; interval spans zero, no memory-saving claim. B2 remains unavailable; LGT4CG novelty/generalization limits remain explicit. Negative/inconclusive outcomes are not removed.
- Full original archive (449,235,501 bytes), controls, analysis and final inventory backed up with complete Azure GET/SHA-256 verification. Raw logits stay private. INC-0128/0132 follow-ups now record independently audited GPU correction; INC-0133 records harmless local path lookup errors.
- Public result: `docs/environment/hdsc-final-evaluation-result.md`, associated provenance and complete derived-analysis manifests. Historical protected results and frozen input/schedule files remain unchanged. Derived counts, hashes, paired effects, JSON, links, incident IDs, frozen schedules and protected historical evidence passed publication validation. GitHub publication follows this checkpoint. H100 remains **DEALLOCATED**; no subsequent start authorized.

## 2026-10-10T22:30:09.845109+00:00 — local manuscript and delivery consolidation; no H100 use

- Base evidence commit: `f179ce927ca803b3fb6da1cd28464f0007646ad5`. User asked to finish the remaining local work and push. No fresh GPU authorization is inferred; no VM/infrastructure mutation or new GPU job. Last confirmed H100 state: **DEALLOCATED**, disk retained.
- Added complete research manuscript draft, explicit completion/submission register and offline evidence-review instructions. Results, frozen schedules, prior experiments and source implementations remain unchanged.
- Rechecked primary literature. Indexed LGT4CG §4.2 supports kernel parameter/dataflow overlap; dynamic scope remains unresolved. The manuscript retains provisional novelty, unavailable B2 comparison, private-original access requirement and bounded model/memory claims. No competitor was run.
- Corrected stale paper status entries. No invented authorship, acceptance, journal submission or public raw-data release. Human authorship/venue/reviewer-access decisions concern submission, not delivery of this draft.
- INC-0134 records a harmless source-path lookup error; INC-0135 records direct publisher access failure and the limited indexed-primary-source fallback. Scientific original data unchanged; no H100 cost in this stage.
- Validation passed: public evidence SHA-256, count arithmetic, exact recomputation of all paired bootstrap effects, every manuscript performance-table row, local Markdown links, unchanged scientific/source/infra trees and unique incident IDs. Existing release guard and secret scan precede push; existing CI checks must pass for the resulting commit. Next task is editorial/scientific review of the delivered draft, not another GPU window.
