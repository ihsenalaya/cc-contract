# Problem definition

An application intends a consumer to read a particular logical object and version.
A CUDA call can complete successfully using a different, live, initialized object.
A protected communication channel does not itself define that application intent.
The verifier asks whether consumed state satisfies that intent at the instrumented
boundary. It does not classify CUDA-valid alternate scheduling as a hardware bug.

Example: two live token buffers have the same shape. Replaying a graph captured
with the old pointer may consume the old token generation. CUDA status alone does
not express which generation the application wanted. A final output comparison
can catch a changed result; it cannot distinguish two states yielding equal output.
[NVIDIA graph parameter semantics](https://docs.nvidia.com/cuda/archive/13.1.1/cuda-programming-guide/04-special-topics/cuda-graphs.html#updating-instantiated-graphs).

RQ1 is mechanism feasibility; RQ2 asks incremental detection value; RQ3 asks online
checking under data-dependent host dispatch; RQ4 asks total application overhead.
RQ2.B3 means CC-Contract, whereas historical search B3 means structural guidance.
Those labels describe different experiments and must not be pooled.
