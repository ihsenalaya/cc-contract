"""Initial E1 development corpus, never an independent evaluation corpus."""

import random
from copy import deepcopy


def scenario(seed: int, family: str) -> dict:
    rng = random.Random(seed)
    size = [1, 2, 7, 32, 65, 128][seed % 6]
    ops = [{"op": "alloc", "buffer": name, "location": loc, "size": size} for name, loc in [("input", "host"), ("gpu", "device"), ("output", "host")]]
    rounds = 2 if family in {"T02", "T05"} else 1
    for generation in range(rounds):
        values = [rng.randrange(-4096, 4097) for _ in range(size)]
        ops += [{"op": "write", "buffer": "input", "generation": generation, "values": values}, {"op": "copy", "source": "input", "target": "gpu", "stream": "upload"}]
        if family == "T03":
            ops += [{"op": "record_event", "event": f"ready-{generation}", "stream": "upload"}, {"op": "wait_event", "event": f"ready-{generation}", "stream": "download"}]
            stream = "download"
        else:
            stream = "upload"
        ops += [{"op": "copy", "source": "gpu", "target": "output", "stream": stream}, {"op": "sync", "stream": stream}, {"op": "observe", "buffer": "output", "generation": generation, "expected": values}]
    ops += [{"op": "free", "buffer": name} for name in ["input", "gpu", "output"]]
    return {"schema_version": 1, "id": f"initial-{family}-{seed:04d}", "seed": seed, "family": family, "operations": ops}


def initial_corpus() -> list[dict]:
    legal = [{"category": "legal", "expected_verdict": "PASS", "mutation": None, "scenario": scenario(i, ["T01", "T02", "T03", "T05"][i % 4])} for i in range(24)]
    mutants = []
    for i, entry in enumerate(legal):
        item = deepcopy(entry)
        item.update(category="semantic_mutant", expected_verdict="FAIL", mutation=["payload_corruption", "stale_generation", "stale_payload"][i % 3])
        item["scenario"]["id"] += "-mutant"
        mutants.append(item)
    invalid = []
    for i in range(12):
        item = deepcopy(legal[i])
        item.update(category="invalid", expected_verdict="INVALID_TEST")
        ops = item["scenario"]["operations"]
        if i % 3 == 0:
            item["scenario"]["operations"] = [op for op in ops if op["op"] != "sync"]
        elif i % 3 == 1:
            # Free the source while its upload is still pending.
            pos = next(j for j, op in enumerate(ops) if op["op"] == "copy")
            ops.insert(pos + 1, {"op": "free", "buffer": "input"})
        else:
            next(op for op in ops if op["op"] == "alloc" and op["buffer"] == "gpu")["size"] += 1
        item["scenario"]["id"] += "-invalid"
        invalid.append(item)
    return legal + mutants + invalid
