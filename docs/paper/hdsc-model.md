# Host–Device State Continuity Model (HDSC v1)

For consumer K, S(K) = (buffer_id, generation, producer, stream, dependency,
consumer, payload_tag). The application declares ExpectedState(K) before injection.
ObservedState(K) combines consumed bytes with executed API bindings from a trusted
adapter. A stream denotes the producer's stream; the consumer stream is the launch
context. Dependencies name unique event epochs, not reusable event-handle strings.

Maintain relations G(buffer, generation), P(producer, buffer, generation),
R(event_epoch, allocation, generation), W(consumer_stream, event_epoch),
B(graph_instance, captured_allocation), and C(consumer, allocation, generation).
A new generation must increase for that logical buffer; pending consumers prevent
reuse. A recorded event retains the version binding at recording, not the latest
version of a mutable map. Graph capture retains a physical allocation binding;
changing a host variable does not update it. A reused graph allocation can hold a
new version only after an ordered transfer; the next consumer has a new intent.

The online API is declare → transferred → recorded → waited → launch → complete.
Only currently executed relations are supplied. At complete, compare all seven
fields and require the expected dependency to refer to the selected allocation
and generation. No list of future operations is a verifier input. This is a bounded
executable relational model, not a mechanized proof of CUDA/PTX memory semantics.

For valid evidence and CUDA_SUCCESS, unequal states produce
STATE_CONTINUITY_VIOLATION; equal states and satisfied dependency produce PASS.
CUDA_ERROR, INVALID_TEST, INFRA_FAILURE and UNSUPPORTED remain separate. CPU
MODEL_SUCCESS exercises the algorithm but never counts as a CUDA observation.

Observation provenance is explicit. The native worker emits buffer/generation,
consumer discriminator and bytes actually used by sum/xor. Producer, stream and
event attribution comes from the trusted CUDA adapter, not GPU attestation.
The Transformer consumes the very tensor snapshot returned to the verifier;
its consumer name also comes from the adapter. These fields are not independently
hardware-observed. No self-consistent malicious forgery detection is claimed.

Implementation: `hdsc_runtime.py`. Historical v0.1 detector/results are unchanged.
The old RQ1 pilot verified only the buffer/generation/payload projection; it is not
retroactively described as a seven-field device observation.
