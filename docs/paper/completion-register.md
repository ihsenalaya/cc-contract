# HDSC delivery and publication status — 11 October 2026

The local research package is complete for the supported, approved HDSC v1
matrix. The [manuscript draft](manuscript.md) assembles the existing evidence.
Completion of this package does not imply that every originally desired
comparison was possible or that a journal submission is ready.

| Item | Status | Evidence / remaining boundary |
|---|---|---|
| C1: state model | Implemented and documented | [HDSC](hdsc-model.md); executable relations, no formal CUDA proof |
| C2: online verifier | Implemented and qualified | [Trust model](threat-model.md); trusted host attribution |
| RQ1 | Historical pilot complete; preserved | [50-run evidence](rq1-existing-evidence.md); no pooling |
| RQ2 direct | Audited | 120 injected + 120 healthy; [results](../environment/hdsc-final-evaluation-result.md) |
| RQ2 Compute Sanitizer | Unavailable on tested CC configuration | Three capability controls; 720 skipped records; no B2 conclusion |
| RQ3 native + healthy corpus | Audited | 50 dynamic streams and 80 separate healthy runs |
| AI fault evaluation | Audited | 40 injected/healthy pairs on pretrained model |
| RQ4 | Audited, bounded scope | Ten valid ON/OFF blocks; all metrics and uncertainty retained |
| Search Random/B3/B4 | Deliberately deferred | Secondary question, zero new search runs; historical campaign unchanged |
| Literature positioning | Updated, novelty challenged | [Matrix](related-work-matrix.md); no claimed universal advantage over LGT4CG |
| Manuscript | Complete research draft | [Manuscript](manuscript.md), linked methods, results and limitations |
| Evidence and reproducibility | Public derived analysis, private originals | [Offline review](../reproducibility/hdsc-offline-audit.md); access required for full raw audit |
| Infrastructure | Retained; last confirmed DEALLOCATED | No new GPU use or infrastructure change in this writing stage |

Before a journal submission, the owner must settle authorship, target venue and
reviewer access to private originals. A specialist review of novelty and the full
LGT4CG comparison is still required. None of these editorial decisions blocks
publication of this repository draft. No submission to a journal, contact with
other people, extra experiment or H100 restart is authorized by this package.

No further H100 window is needed to assemble or review the existing evidence.
Extending the claims would be new work, with its own protocol and approval.
