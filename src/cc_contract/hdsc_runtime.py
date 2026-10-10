"""Online relational verifier. No future trace, seed, scenario or fault input."""
from dataclasses import dataclass, asdict
import hashlib


@dataclass(frozen=True)
class State:
    buffer_id: int
    generation: int
    producer: str
    stream: str
    dependency: str
    consumer: str
    payload_tag: str

    def public(self):
        return asdict(self)


class Ledger:
    """Trusted application intents and executed API bindings are separate inputs.

    The API adapter, not CUDA itself, supplies producer/stream/event attribution.
    Payload bytes must come from the consumer's actual input snapshot. This does
    not establish cryptographic integrity of a compromised adapter or consumer.
    """
    def __init__(self):
        self.generations = {}
        self.slots = {}
        self.events = {}
        self.waits = set()
        self.graphs = {}
        self.pending = {}

    def declare(self, buffer_id, generation, payload, producer, stream, event, consumer):
        if (type(buffer_id) is not int or type(generation) is not int or
                generation <= self.generations.get(buffer_id, 0) or
                not isinstance(payload, bytes) or not payload or
                any(not isinstance(x, str) or not x for x in (producer, stream, event, consumer))):
            raise ValueError("Invalid intent or non-increasing buffer generation")
        if any(s.buffer_id == buffer_id for s in self.pending.values()):
            raise ValueError("Cannot reuse a buffer with an unretired consumer")
        self.generations[buffer_id] = generation
        return State(buffer_id, generation, producer, stream, event, consumer,
                     hashlib.sha256(payload).hexdigest())

    def transferred(self, slot, executed_state):
        if any(binding == slot for binding, _ in self.pending):
            raise ValueError("Cannot overwrite a pending consumer allocation")
        self.slots[slot] = executed_state

    def recorded(self, event, slot):
        if event in self.events:
            raise ValueError("Use event epochs; event reuse must have a new identity")
        self.events[event] = (slot, self.slots[slot])

    def waited(self, stream, event):
        if event not in self.events:
            raise ValueError("Wait on unrecorded event epoch")
        self.waits.add((stream, event))

    def captured(self, graph, slot):
        if slot not in self.slots:
            raise ValueError("Capture references an unknown allocation")
        self.graphs[graph] = slot

    def launch(self, expected, slot, consumer_stream, *, graph=None):
        selected = self.graphs[graph] if graph is not None else slot
        if selected not in self.slots or (selected, expected.consumer) in self.pending:
            raise ValueError("Unknown or already active consumer binding")
        self.pending[(selected, expected.consumer)] = expected
        return selected

    def complete(self, expected, selected, consumer_stream, execution_status, consumed,
                 observed_buffer, observed_generation, observed_consumer):
        key = (selected, expected.consumer)
        if self.pending.pop(key, None) != expected:
            return {"classification": "INVALID_TEST", "reason": "missing_launch"}
        if execution_status in ("CUDA_ERROR", "UNSUPPORTED", "INFRA_FAILURE"):
            return {"classification": execution_status}
        if execution_status not in ("CUDA_SUCCESS", "MODEL_SUCCESS") or not isinstance(consumed, bytes):
            return {"classification": "INVALID_TEST"}
        binding = self.slots[selected]
        observed = State(observed_buffer, observed_generation, binding.producer, binding.stream,
                         binding.dependency, observed_consumer, hashlib.sha256(consumed).hexdigest())
        differences = [name for name in asdict(expected) if getattr(expected, name) != getattr(observed, name)]
        dependency = self.events.get(expected.dependency)
        if (consumer_stream, expected.dependency) not in self.waits or dependency != (selected, binding):
            differences.append("dependency_binding")
        return {"classification": "STATE_CONTINUITY_VIOLATION" if differences else "PASS",
                "expected_state": expected.public(), "observed_state": observed.public(),
                "mismatches": differences, "attribution": {
                    "device_observed": ["buffer_id", "generation", "payload_tag", "consumer"],
                    "trusted_API_adapter": ["producer", "stream", "dependency"]}}
