"""Fault-blind state-continuity detector; no injector imports or fault arguments."""
from dataclasses import dataclass
import hashlib
import struct

WORDS = 16
PACKET_WORDS = WORDS + 3
MASK = (1 << 32) - 1


@dataclass(frozen=True)
class ExpectedState:
    buffer_id: int
    generation_id: int
    payload: tuple[int, ...]
    producer: str = "host-producer"
    stream: str = "producer-stream"
    dependency: str = "generation-2-ready"
    consumer: str = "consume"

    @property
    def payload_tag(self):
        return hashlib.sha256(struct.pack("<16I", *self.payload)).hexdigest()

    def public(self):
        return dict(buffer_id=self.buffer_id, generation_id=self.generation_id,
                    payload_tag=self.payload_tag, producer=self.producer,
                    stream=self.stream, dependency=self.dependency, consumer=self.consumer)


def classify(expected, observation):
    """Validate an actual consumer record then compare it with a trusted contract.

    Payload comparisons, not just header tags, prevent stale payload being hidden
    by rewriting identity/generation. Self-consistent malicious forgery is outside
    this instrumentation threat model. The caller supplies no requested verdict.
    """
    if not isinstance(expected, ExpectedState) or len(expected.payload) != WORDS:
        return {"classification": "INVALID_TEST"}
    if not isinstance(observation, dict):
        return {"classification": "INFRA_FAILURE"}
    status = observation.get("execution_status")
    backend = observation.get("backend")
    if status in ("CUDA_ERROR", "UNSUPPORTED", "INFRA_FAILURE"):
        return {"classification": status}
    if (backend, status) not in (("cpu-model", "MODEL_SUCCESS"), ("cuda", "CUDA_SUCCESS")):
        return {"classification": "INFRA_FAILURE"}
    raw = observation.get("consumed_words")
    result = observation.get("consumer_sum")
    if (not isinstance(raw, list) or len(raw) != PACKET_WORDS or
            any(type(x) is not int or not 0 <= x <= MASK for x in raw) or
            type(result) is not int or not 0 <= result <= MASK):
        return {"classification": "INFRA_FAILURE"}
    if raw[2] != WORDS or sum(raw[3:]) & MASK != result:
        return {"classification": "INVALID_TEST"}
    tag = hashlib.sha256(struct.pack("<16I", *raw[3:])).hexdigest()
    observed = dict(observed_buffer_id=raw[0], observed_generation=raw[1],
                    observed_payload_tag=tag)
    mismatches = [name for name, actual, wanted in (
        ("buffer_id", raw[0], expected.buffer_id),
        ("generation_id", raw[1], expected.generation_id),
        ("payload", tuple(raw[3:]), expected.payload)) if actual != wanted]
    return dict(classification="STATE_CONTINUITY_VIOLATION" if mismatches else "PASS",
                observed_state=observed, mismatches=mismatches)
