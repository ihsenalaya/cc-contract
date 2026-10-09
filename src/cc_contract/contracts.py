"""Conservative legality checks for a small, explicitly bounded sequence IR.

This is a model contract, not a complete CUDA/PyTorch legality checker.
Host operations are synchronous; copies are deferred in ordered stream queues.
Cross-stream dependencies require a recorded event and an explicit wait.
Buffer reuse/free require completion of every outstanding use.
"""

from dataclasses import dataclass


class InvalidScenario(ValueError):
    pass


class UnsupportedScenario(ValueError):
    pass


@dataclass
class Buffer:
    location: str
    size: int
    generation: int = -1
    writer: int | None = None


def validate(scenario: dict) -> None:
    if scenario.get("schema_version") != 1:
        raise InvalidScenario("C0: unsupported schema version")
    if scenario.get("family") in {"T07", "T08"}:
        raise UnsupportedScenario("C0: mapped memory/graphs not implemented")
    if scenario.get("family") not in {"T01", "T02", "T03", "T04", "T05", "T06"}:
        raise InvalidScenario("C0: unknown family")
    operations = scenario.get("operations")
    if not isinstance(operations, list) or not operations:
        raise InvalidScenario("C0: operations must be a nonempty list")
    buffers: dict[str, Buffer] = {}
    # Closure of predecessor operations for each stream/event/completed host state.
    streams: dict[str, set[int]] = {}
    events: dict[str, set[int]] = {}
    completed: set[int] = set()
    uses: dict[str, set[int]] = {}
    outstanding: set[int] = set()
    observed = 0

    def require(name: str) -> Buffer:
        if name not in buffers:
            raise InvalidScenario(f"C2: unknown/freed buffer {name}")
        return buffers[name]

    def idle(name: str) -> None:
        if uses.get(name, set()) - completed:
            raise InvalidScenario(f"C2: outstanding use of {name}")

    def ready(buffer: Buffer, predecessors: set[int]) -> None:
        if buffer.generation < 0:
            raise InvalidScenario("C3: uninitialized source")
        if buffer.writer is not None and buffer.writer not in predecessors:
            raise InvalidScenario("C1: missing synchronization/dependency")

    try:
        for index, op in enumerate(operations):
            kind = op["op"]
            if kind == "alloc":
                name = op["buffer"]
                if not isinstance(name, str) or not name or name in buffers:
                    raise InvalidScenario("C2: invalid/duplicate allocation")
                if op["location"] not in {"host", "device"}:
                    raise InvalidScenario("C0: unknown location")
                if type(op["size"]) is not int or not 1 <= op["size"] <= 65536:
                    raise InvalidScenario("C0: size outside supported model range")
                buffers[name] = Buffer(op["location"], op["size"])
                uses[name] = set()
            elif kind == "write":
                name = op["buffer"]
                b = require(name)
                idle(name)
                if b.location != "host":
                    raise InvalidScenario("C0: direct host writes require host buffer")
                values = op["values"]
                if not isinstance(values, list) or len(values) != b.size or any(type(v) is not int for v in values):
                    raise InvalidScenario("C0: integer payload/shape mismatch")
                if type(op["generation"]) is not int or op["generation"] <= b.generation:
                    raise InvalidScenario("C3: generation must increase")
                b.generation, b.writer = op["generation"], None
            elif kind == "copy":
                source, target = op["source"], op["target"]
                src, dst = require(source), require(target)
                if source == target or src.size != dst.size:
                    raise InvalidScenario("C0: alias/shape mismatch")
                stream = op["stream"]
                if not isinstance(stream, str) or not stream:
                    raise InvalidScenario("C0: invalid stream")
                previous = streams.setdefault(stream, set()) | completed
                ready(src, previous)
                # RAW, WAR and WAW on a target must be ordered, not only last writes.
                if uses[target] - previous:
                    raise InvalidScenario("C2: unordered target reuse")
                dst.generation, dst.writer = src.generation, index
                streams[stream] = previous | {index}
                outstanding.add(index)
                uses[source].add(index)
                uses[target].add(index)
            elif kind == "record_event":
                name = op["event"]
                if name in events:
                    raise InvalidScenario("C4: event identifier reuse unsupported")
                events[name] = set(streams.get(op["stream"], set())) | completed
            elif kind == "wait_event":
                if op["event"] not in events:
                    raise InvalidScenario("C1: unknown event")
                stream = op["stream"]
                streams[stream] = streams.get(stream, set()) | events[op["event"]] | completed
            elif kind == "sync":
                completed |= streams.get(op["stream"], set())
            elif kind == "observe":
                b = require(op["buffer"])
                if b.location != "host":
                    raise InvalidScenario("C0: observation requires host buffer")
                ready(b, completed)
                if uses[op["buffer"]] - completed:
                    raise InvalidScenario("C1: observation before completion")
                if type(op["generation"]) is not int or op["generation"] != b.generation:
                    raise InvalidScenario("C3: observation generation mismatch")
                if not isinstance(op["expected"], list) or len(op["expected"]) != b.size or any(type(v) is not int for v in op["expected"]):
                    raise InvalidScenario("C0: malformed expected payload")
                observed += 1
            elif kind == "free":
                idle(op["buffer"])
                require(op["buffer"])
                del buffers[op["buffer"]]
            else:
                raise InvalidScenario(f"C0: unknown operation {kind}")
        if not observed:
            raise InvalidScenario("C0: scenario has no observable oracle")
        if outstanding - completed:
            raise InvalidScenario("C1: scenario finishes with pending operations")
    except (KeyError, TypeError) as error:
        raise InvalidScenario(f"C0: malformed operation: {error}") from error
