"""Deterministic legal IR generators; hardware capabilities are qualified separately."""
import random
from .contracts import validate

FAMILIES = tuple(f"T{i:02d}" for i in range(1, 9))
BOUNDARIES = (1, 2, 31, 32, 33, 255, 256, 257, 4095, 4096, 4097, 65536)


def generate(seed, family, rounds=3, size=None, streams=2, replay_count=2):
    if family not in FAMILIES or not 1 <= rounds <= 8 or not 1 <= streams <= 4:
        raise ValueError("Generator parameters outside protocol bounds")
    if family == "T03" and streams < 2:
        raise ValueError("T03 requires two distinct streams")
    size = size or BOUNDARIES[seed % len(BOUNDARIES)]
    rng = random.Random(seed)
    slots = 2 if family == "T04" else 1
    if family in {"T01", "T06", "T07"}:
        rounds = 1
    ops = []
    for slot in range(slots):
        for name, location in [("input", "host"), ("device", "device"), ("output", "host")]:
            shape = [size] if family != "T06" or size % 2 else [2, size // 2]
            op = {"op": "alloc", "buffer": f"{name}{slot}", "location": location, "size": size, "shape": shape}
            if family == "T07" and name == "input":
                op["memory"] = "mapped"
            ops.append(op)
    for generation in range(rounds):
        expected = {}
        for slot in range(slots):
            values = [rng.randrange(-4096, 4097) for _ in range(size)]
            expected[slot] = values
            ops.append({"op": "write", "buffer": f"input{slot}", "generation": generation, "values": values})
            upload = f"stream{slot % streams}"
            download = f"stream{(slot + 1) % streams}" if family == "T03" else upload
            if family == "T08":
                if generation == 0:
                    ops.append({"op": "define_graph", "graph": "copies", "stream": upload, "operations": [
                        {"op": "copy", "source": "input0", "target": "device0", "stream": upload},
                        {"op": "copy", "source": "device0", "target": "output0", "stream": upload}]})
                ops.append({"op": "replay_graph", "graph": "copies", "repeats": replay_count})
            else:
                ops.append({"op": "mapped_copy" if family == "T07" else "copy", "source": f"input{slot}", "target": f"device{slot}", "stream": upload})
                if download != upload:
                    event = f"ready{generation}"
                    ops.extend([{"op": "record_event", "event": event, "stream": upload}, {"op": "wait_event", "event": event, "stream": download}])
                ops.append({"op": "copy", "source": f"device{slot}", "target": f"output{slot}", "stream": download})
        # Both slots are submitted before observing: actual double buffering.
        for slot in range(slots):
            sink = f"stream{(slot + 1) % streams}" if family == "T03" else f"stream{slot % streams}"
            ops.extend([{"op": "sync", "stream": sink}, {"op": "observe", "buffer": f"output{slot}", "generation": generation, "expected": expected[slot]}])
    if family == "T08":
        ops.append({"op": "destroy_graph", "graph": "copies"})
    for slot in range(slots):
        for name in ["input", "device", "output"]:
            ops.append({"op": "free", "buffer": f"{name}{slot}"})
    result = {"schema_version": 1, "id": f"generated-{family}-{seed}", "seed": seed, "family": family, "operations": ops,
              "generator": {"version": 2, "rounds": rounds, "slots": slots, "size": size, "streams": streams, "replay_count": replay_count}}
    validate(result)
    return result


def qualification_corpus():
    return [generate(1000 + i, family, size=n) for i, (family, n) in enumerate((f, n) for f in FAMILIES for n in BOUNDARIES)]


def features(scenario):
    """Coverage keys are software features, never defect counts."""
    ops = scenario["operations"]
    structural = {"family:" + scenario["family"]}
    structural |= {"operation:" + o["op"] for o in ops}
    structural |= {"shape:" + str(o.get("shape", [o["size"]])) for o in ops if o["op"] == "alloc"}
    temporal = {"transition:" + a["op"] + ">" + b["op"] for a, b in zip(ops, ops[1:])}
    temporal |= {"generation:" + str(o["generation"]) for o in ops if o["op"] == "observe"}
    temporal |= {"triple:" + ">".join(o["op"] for o in ops[i:i+3]) for i in range(len(ops)-2)}
    return structural, temporal
