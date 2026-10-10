# RQ3 — online, data-dependent execution

The native persistent worker allocates three packets and two streams once, then
accepts one request after its previous response. Host dispatch selects logical
buffer, sum or xor consumer, and graph/direct path using the preceding actual
output. Generations increase independently by buffer. Requests stop after 4–12
steps depending on outputs. Allocations are reused only after completion. The
verifier never receives seed, injection flag, termination rule or future schedule.

A graph records one fixed subcomputation; this does not pre-record the entire
application trace. RQ3 tests dynamic host dispatch among reusable computations,
not data-dependent control flow inside a single captured CUDA graph. The PyTorch
workload similarly branches between graph and eager model calls using generated
tokens. CUDA Graphs themselves impose static capture constraints.
[PyTorch 2.8 CUDA Graph semantics](https://docs.pytorch.org/docs/2.8/notes/cuda.html#cuda-graphs).

Ten reserved blocks × (healthy + L1 + L2 + C1 + C2) = 50 native request streams.
Each injected stream attempts the fault at step 2; later dispatch may diverge.
Record full realized operations/observations, number of steps, generations, buffers,
consumer variants and first detection. Compare the paired prefix before injection;
do not demand identical later trajectories after a fault alters the result.

A separately seeded healthy corpus covers single stream, multiple streams, event
dependencies, double buffering, graph replay, generation reuse, dynamic branch,
and the trained Transformer. Eight patterns × ten blocks = 80 reserved runs.
Its outputs must not be inspected for tuning before freeze. CPU development
controls validate implementation; they are not the reserved false-positive corpus.

Primary RQ3 claim requires successful actual GPU execution, valid online witnesses,
multiple realized paths, correct healthy handling and detection of activated faults.
One can validate these local properties without claiming that LGT4CG cannot handle
any of these inputs: that stronger comparative assertion remains unverified.
