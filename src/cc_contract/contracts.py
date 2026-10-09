"""Conservative legality checks for a small, explicitly bounded sequence IR.

This is a model contract, not a complete CUDA/PyTorch legality checker.
Host operations are synchronous; copies are deferred in ordered stream queues.
Cross-stream dependencies require a recorded event and an explicit wait.
Buffer reuse/free require completion of every outstanding use.
"""

from dataclasses import dataclass
import math
import re


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
    memory: str = "pinned"


def validate(scenario: dict) -> None:
    if scenario.get("schema_version") != 1:
        raise InvalidScenario("C0: unsupported schema version")
    if scenario.get("family") not in {f"T{i:02d}" for i in range(1, 9)}:
        raise InvalidScenario("C0: unknown family")
    operations = scenario.get("operations")
    if not isinstance(operations, list) or not 1 <= len(operations) <= 4096:
        raise InvalidScenario("C0: operations must be a nonempty list")
    if scenario.get("family") == "T07" and not any(o.get("op") == "mapped_copy" for o in operations if isinstance(o, dict)):
        raise InvalidScenario("C0: mapped family requires mapped kernel operation")
    if scenario.get("family") == "T08" and not any(o.get("op") == "replay_graph" for o in operations if isinstance(o, dict)):
        raise InvalidScenario("C0: graph family requires graph replay")
    buffers: dict[str, Buffer] = {}
    # Closure of predecessor operations for each stream/event/completed host state.
    streams: dict[str, set[int]] = {}
    events: dict[str, set[int]] = {}
    completed: set[int] = set()
    uses: dict[str, set[int]] = {}
    outstanding: set[int] = set()
    observed = 0
    graphs = {}
    clock = 0

    def identifier(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value):
            raise InvalidScenario("C0: malformed identifier")
        return value

    def require(name: str) -> Buffer:
        identifier(name)
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

    def copy_operation(op):
        nonlocal clock
        source, target = op["source"], op["target"]
        src, dst = require(source), require(target)
        if source == target or src.size != dst.size:
            raise InvalidScenario("C0: alias/shape mismatch")
        if op["op"] == "mapped_copy" and (src.location != "host" or src.memory != "mapped" or dst.location != "device"):
            raise InvalidScenario("C0: mapped kernel requires mapped host source and device target")
        stream = identifier(op["stream"])
        previous = streams.setdefault(stream, set()) | completed
        ready(src, previous)
        if uses[target] - previous:
            raise InvalidScenario("C2: unordered target reuse")
        dst.generation, dst.writer = src.generation, clock
        streams[stream] = previous | {clock}
        outstanding.add(clock)
        uses[source].add(clock)
        uses[target].add(clock)
        clock += 1

    try:
        for index, op in enumerate(operations):
            kind = op["op"]
            if kind == "alloc":
                name = op["buffer"]
                identifier(name)
                if name in buffers:
                    raise InvalidScenario("C2: invalid/duplicate allocation")
                if op["location"] not in {"host", "device"}:
                    raise InvalidScenario("C0: unknown location")
                if type(op["size"]) is not int or not 1 <= op["size"] <= 65536:
                    raise InvalidScenario("C0: size outside supported model range")
                shape = op.get("shape", [op["size"]])
                if not isinstance(shape, list) or not 1 <= len(shape) <= 4 or any(type(v) is not int or v < 1 for v in shape) or math.prod(shape) != op["size"]:
                    raise InvalidScenario("C0: shape/product mismatch")
                memory = op.get("memory", "pinned")
                if memory not in {"pinned", "mapped"} or (memory == "mapped" and op["location"] != "host"):
                    raise InvalidScenario("C0: unsupported allocation memory kind")
                buffers[name] = Buffer(op["location"], op["size"], memory=memory)
                uses[name] = set()
            elif kind == "write":
                name = op["buffer"]
                b = require(name)
                idle(name)
                if b.location != "host":
                    raise InvalidScenario("C0: direct host writes require host buffer")
                values = op["values"]
                if not isinstance(values, list) or len(values) != b.size or any(type(v) is not int or not -(2**31) <= v < 2**31 for v in values):
                    raise InvalidScenario("C0: integer payload/shape mismatch")
                if type(op["generation"]) is not int or not 0 <= op["generation"] < 2**31 or op["generation"] <= b.generation:
                    raise InvalidScenario("C3: generation must increase")
                b.generation, b.writer = op["generation"], None
            elif kind in {"copy", "mapped_copy"}:
                copy_operation(op)
            elif kind == "record_event":
                name = identifier(op["event"])
                identifier(op["stream"])
                if name in events:
                    raise InvalidScenario("C4: event identifier reuse unsupported")
                events[name] = set(streams.get(op["stream"], set())) | completed
            elif kind == "wait_event":
                if op["event"] not in events:
                    raise InvalidScenario("C1: unknown event")
                stream = identifier(op["stream"])
                streams[stream] = streams.get(stream, set()) | events[op["event"]] | completed
            elif kind == "sync":
                identifier(op["stream"])
                completed |= streams.get(op["stream"], set())
            elif kind == "define_graph":
                name, stream = identifier(op["graph"]), identifier(op["stream"])
                nodes = op["operations"]
                if name in graphs or not isinstance(nodes, list) or not 1 <= len(nodes) <= 64:
                    raise InvalidScenario("C4: malformed or duplicate graph definition")
                for node in nodes:
                    if node["op"] != "copy" or node["stream"] != stream:
                        raise InvalidScenario("C4: graph supports one-stream copies only")
                    src, dst = require(node["source"]), require(node["target"])
                    if node["source"] == node["target"] or src.size != dst.size:
                        raise InvalidScenario("C0: graph alias/shape mismatch")
                graphs[name] = nodes
            elif kind == "replay_graph":
                name = identifier(op["graph"])
                if name not in graphs or type(op["repeats"]) is not int or not 1 <= op["repeats"] <= 64:
                    raise InvalidScenario("C4: unknown graph/invalid replay count")
                for _ in range(op["repeats"]):
                    for node in graphs[name]:
                        copy_operation(node)
            elif kind == "destroy_graph":
                name = identifier(op["graph"])
                if name not in graphs:
                    raise InvalidScenario("C4: unknown graph")
                for node in graphs[name]:
                    idle(node["source"])
                    idle(node["target"])
                del graphs[name]
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
                if any(op["buffer"] in {node["source"], node["target"]} for nodes in graphs.values() for node in nodes):
                    raise InvalidScenario("C4: live graph retains buffer")
                idle(op["buffer"])
                require(op["buffer"])
                del buffers[op["buffer"]]
            else:
                raise InvalidScenario(f"C0: unknown operation {kind}")
        if not observed:
            raise InvalidScenario("C0: scenario has no observable oracle")
        if outstanding - completed:
            raise InvalidScenario("C1: scenario finishes with pending operations")
        if graphs or buffers:
            raise InvalidScenario("C2/C4: scenario retains allocations or graphs")
    except (KeyError, TypeError) as error:
        raise InvalidScenario(f"C0: malformed operation: {error}") from error
