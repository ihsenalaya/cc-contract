# Limitations and publication gates

- RQ1 is a deterministic injected-fault pilot. No new NVIDIA vulnerability or
  naturally occurring software defect was discovered.
- HDSC trusts intent construction and instrumentation. Producer/stream/event
  attribution is host-side; the AI consumer name is host-side too. This is not a
  fully device-attested seven-field monitor or a substitute for GPU attestation.
- Native packet and tiny-language-model boundaries are bounded. General kernels,
  concurrency, arbitrary graph mutation and production serving remain untested.
- Equal-output faults are constructed; their frequency is unknown. Exact B1 is
  expected to work on changed outputs, and that positive baseline result is kept.
- Racecheck was excluded from the plan. Actual healthy capability controls for
  memcheck, initcheck and synccheck explicitly rejected the tested CC environment;
  720 dependent jobs were not executed. B2 comparison remains unavailable.
  Unsupported is never a clean/missed result.
- LGT4CG metadata verification overlaps this problem. Available primary material
  supports that overlap but does not settle its entire dynamic capability. The
  scientific gap is provisional; no categorical novelty claim is justified.
- The trained TinyStories model is small and uses fixed input width, no KV cache.
  It supports a real-workload boundary test, not a Qwen7B performance claim.
- Ten blocks give limited precision. Zero healthy alerts cannot establish a
  universally small false-positive rate. Bootstrap results are descriptive for
  this corpus, conditional on independent blocks, with repeated weights/inputs.
- The [supported RQ2–RQ4 GPU matrix](../environment/hdsc-final-evaluation-result.md)
  is independently audited, with ten valid paired overhead blocks. Actual Azure
  billing and independent-host replication are not established. Local CPU results
  qualify code paths; local CUDA compilation is not CUDA execution.
- An interrupted attempt exposed reserved inputs; it is excluded as a whole.
  The later evaluation is not an untouched holdout. Native and AI sections have
  distinct recorded sources/images; the AI-only capture correction passed exact
  original/adapted/replay GPU logits gates without changing the frozen workload.
- Peak allocated GPU memory varies with process/allocator history. Its paired
  interval spans zero; the negative estimate does not establish a memory saving.
  Small-model timing includes harness overhead and is not production throughput.
- Global deadline may censor a future campaign. Preserve partial runs and stop;
  any continuation needs a new approved plan. No favorable-result stopping rule.
