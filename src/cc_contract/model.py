"""CPU-only deferred-copy model and exact integer/metadata oracle."""

from copy import deepcopy
from .contracts import validate


def execute(scenario: dict, mutation: str | None = None) -> list[dict]:
    validate(scenario)
    if mutation not in {None, "payload_corruption", "stale_generation", "stale_payload"}:
        raise ValueError("Unknown controlled semantic mutation")
    buffers: dict[str, dict] = {}
    queue: dict[str, list] = {}
    events: dict[str, tuple[str, int]] = {}
    observations = []

    def flush(stream: str, limit: int | None = None) -> None:
        items = queue.setdefault(stream, [])
        upto = len(items) if limit is None else limit
        for i in range(upto):
            action = items[i]
            if action is None:
                continue
            if action[0] == "wait":
                flush(action[1], action[2])
            else:
                _, source, target = action
                buffers[target] = deepcopy(buffers[source])
            items[i] = None

    for op in scenario["operations"]:
        kind = op["op"]
        if kind == "alloc":
            buffers[op["buffer"]] = {"values": [0] * op["size"], "generation": -1}
        elif kind == "write":
            buffers[op["buffer"]] = {"values": list(op["values"]), "generation": op["generation"]}
        elif kind == "copy":
            queue.setdefault(op["stream"], []).append(("copy", op["source"], op["target"]))
        elif kind == "record_event":
            events[op["event"]] = (op["stream"], len(queue.setdefault(op["stream"], [])))
        elif kind == "wait_event":
            queue.setdefault(op["stream"], []).append(("wait", *events[op["event"]]))
        elif kind == "sync":
            flush(op["stream"])
        elif kind == "free":
            del buffers[op["buffer"]]
        elif kind == "observe":
            actual = deepcopy(buffers[op["buffer"]])
            if mutation == "payload_corruption":
                actual["values"][0] ^= 1
            elif mutation == "stale_generation":
                actual["generation"] -= 1
            elif mutation == "stale_payload":
                actual["values"] = [v - 1 for v in actual["values"]]
            correct = actual["values"] == op["expected"] and actual["generation"] == op["generation"]
            observations.append({"buffer": op["buffer"], "expected": {"values": op["expected"], "generation": op["generation"]}, "observed": actual, "verdict": "PASS" if correct else "FAIL", "reason": "exact_integer_and_generation_comparison", "controlled_mutation": mutation})
    return observations
