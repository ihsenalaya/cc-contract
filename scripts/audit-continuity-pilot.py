"""Independent post-run recomputation; imports neither injector nor detector."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct


def audit(rows, schedule):
    if len(rows) != 50 or len(schedule) != 50:
        raise ValueError("Exactly 50 runs required for a complete audit")
    counts = Counter()
    for record, planned in zip(rows, schedule):
        if any(record.get(key) != value for key, value in planned.items()):
            raise ValueError("Schedule or ordering changed")
        if type(record["seed"]) is not int:
            raise ValueError("Noninteger seed")
        expected_bytes = hashlib.shake_256(
            f'state-continuity-pilot-v0.1/{record["seed"]}/1/2'.encode()).digest(64)
        expected_words = [1, 2, 16, *struct.unpack("<16I", expected_bytes)]
        observation = record["observation"]
        if observation["backend"] != record["backend"]:
            raise ValueError("Backend identity differs")
        status = {"cpu-model": "MODEL_SUCCESS", "cuda": "CUDA_SUCCESS"}[record["backend"]]
        if observation["execution_status"] != status:
            raise ValueError("Execution failed; preserve partial report, no complete audit")
        if record["backend"] == "cuda":
            raw = record["raw_worker"]
            if raw["returncode"] != 0 or json.loads(raw["stdout"]) != observation:
                raise ValueError("Original worker response differs")
        words = observation["consumed_words"]
        if len(words) != 19 or any(type(x) is not int or not 0 <= x < 2 ** 32 for x in words):
            raise ValueError("Invalid raw words")
        if words[2] != 16 or sum(words[3:]) % (2 ** 32) != observation["consumer_sum"]:
            raise ValueError("Consumer computation differs")
        observed_tag = hashlib.sha256(struct.pack("<16I", *words[3:])).hexdigest()
        expected_tag = hashlib.sha256(expected_bytes).hexdigest()
        wanted_class = "PASS" if words == expected_words else "STATE_CONTINUITY_VIOLATION"
        if record["verdict"]["classification"] != wanted_class:
            raise ValueError("Detector verdict differs from independent comparison")
        if record["expected_state"] != dict(buffer_id=1, generation_id=2, payload_tag=expected_tag,
                                            producer="host-producer", stream="producer-stream",
                                            dependency="generation-2-ready", consumer="consume"):
            raise ValueError("Trusted expected contract altered")
        wanted_observed = dict(observed_buffer_id=words[0], observed_generation=words[1], observed_payload_tag=observed_tag)
        if record["verdict"]["observed_state"] != wanted_observed:
            raise ValueError("Observed-state tags altered")
        mismatches = [key for key, changed in (("buffer_id", words[0] != 1),
                      ("generation_id", words[1] != 2), ("payload", words[3:] != expected_words[3:])) if changed]
        if record["verdict"]["mismatches"] != mismatches:
            raise ValueError("Mismatch dimensions altered")
        signature = [2, 2] if record["fault"] == "C2" else [1, 1]
        if record["activated"] != bool(record["active"] and words[:2] == signature):
            raise ValueError("Activation claim altered")
        for metric in ("execution_ns", "detection_ns"):
            if type(record[metric]) is not int or record[metric] < 0:
                raise ValueError("Invalid timing")
        counts[record["group"] + "/" + wanted_class] += 1
    return dict(state="PASS_INDEPENDENT_CONTINUITY_AUDIT", runs=50, counts=dict(counts),
                real_cuda=all(row["backend"] == "cuda" for row in rows),
                oracle_and_injector_imported=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=Path, required=True)
    p.add_argument("--schedule", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    rows = [json.loads(line) for line in args.runs.read_text().splitlines()]
    result = audit(rows, json.loads(args.schedule.read_text()))
    result["runs_sha256"] = hashlib.sha256(args.runs.read_bytes()).hexdigest()
    result["schedule_sha256"] = hashlib.sha256(args.schedule.read_bytes()).hexdigest()
    with args.output.open("x") as f:
        f.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
