"""Versioned HDSC inputs. Seeds vary states, never inflate distinct fault causes."""
import hashlib
import json
import random
import struct

VERSION = "hdsc-evaluation-v1"
FAULTS = ("L1", "L2", "C1", "C2")
PROFILES = ("changed-output", "equal-payload", "sum-collision")
SPLITS = {"development": tuple(range(82000, 82002)),
          "reserved_evaluation": tuple(range(93000, 93010))}
SOURCES = {
    "L1": "MUTGPU ICST2020 IV-A.2.b; adapted host-event dependency, not identical barrier operator",
    "L2": "NVIDIA CUDA Graphs: captured kernel parameters require explicit update",
    "C1": "CC-Contract proposed stale-generation model",
    "C2": "CC-Contract proposed compatible-buffer substitution model",
}


def packets(seed, profile, buffer_id=1, generation=2):
    if profile not in PROFILES or generation < 2 or buffer_id < 1:
        raise ValueError("Invalid benchmark state")
    raw = hashlib.shake_256(f"{VERSION}/{seed}/{buffer_id}/{generation}".encode()).digest(64)
    wanted = list(struct.unpack("<16I", raw))
    wrong = wanted.copy()
    if profile == "changed-output":
        wrong[0] = (wrong[0] + 1) % 2**32
    elif profile == "sum-collision":
        wrong[0] = (wrong[0] + 1) % 2**32
        wrong[1] = (wrong[1] - 1) % 2**32
    # equal-payload deliberately changes identity/version but not any payload byte.
    states = ((buffer_id, generation - 1, wrong), (buffer_id, generation, wanted),
              (buffer_id + 100, generation, wrong))
    return [struct.pack("<19I", identity, version, 16, *words) for identity, version, words in states]


def state(packet):
    values = struct.unpack("<19I", packet)
    return {"buffer_id": values[0], "generation": values[1],
            "payload_tag": hashlib.sha256(packet[12:]).hexdigest()}


def benchmark():
    targets = []
    for split, seeds in SPLITS.items():
        for block, seed in enumerate(seeds):
            for fault in FAULTS:
                for profile in PROFILES:
                    data = packets(seed, profile, 1 + block % 3, 2 + block)
                    targets.append({"fault_id": f"{split}-{block}-{fault}-{profile}",
                        "split": split, "block": block, "fault_class": fault,
                        "cause_equivalence": fault, "state_variant": profile,
                        "source": SOURCES[fault], "seed": seed,
                        "buffers": [state(data[1])["buffer_id"], state(data[2])["buffer_id"]],
                        "generations": [state(data[0])["generation"], state(data[1])["generation"]],
                        "streams": ["producer", "consumer"], "events": ["E1", "E2"],
                        "dependencies": [{"from": "producer/E2", "to": "consumer/consume"}],
                        "consumer": "consume-sum-u32", "expected_state": {
                            **state(data[1]), "producer": "host-producer", "stream": "producer",
                            "dependency": "E2", "consumer": "consume-sum-u32"},
                        "reachable_wrong_state": {
                            **state(data[2 if fault == "C2" else 0]),
                            "producer": "other-host-producer" if fault == "C2" else "host-producer",
                            "stream": "producer", "dependency": "B-ready" if fault == "C2" else "E1",
                            "consumer": "consume-sum-u32"},
                        "activation_condition": "Successful consumer bytes equal reachable_wrong_state",
                        "CUDA_validity_requirement": "Live allocations; initialized reads; ordered writes; no overlapping write/read",
                        "output_effect": "sum differs by one modulo 2^32" if profile == "changed-output" else "identical final sum by construction",
                        "packet_sha256": [hashlib.sha256(p).hexdigest() for p in data]})
    return {"version": VERSION, "distinct_causes": 4, "profiles_per_cause": 3,
            "seed_policy": "Independent blocks; seeded variants are not new defect causes",
            "targets": targets}


def schedule(split):
    if split not in SPLITS:
        raise ValueError("Unknown split")
    rng = random.Random(301026 if split == "development" else 401026)
    rows = []
    for block in range(len(SPLITS[split])):
        group = []
        for target in benchmark()["targets"]:
            if target["split"] == split and target["block"] == block:
                group.extend({"target": target, "active": active, "tool": tool}
                             for active in (False, True)
                             for tool in ("direct", "memcheck", "initcheck", "synccheck"))
        rng.shuffle(group)
        rows.extend(group)
    return [dict(run_id=i, **r) for i, r in enumerate(rows)]


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
