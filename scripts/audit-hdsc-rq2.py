"""Recompute RQ2 evidence without importing the injector or either detector."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct


def audit(path):
    counts = Counter()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    seen = set()
    for row in rows:
        target = row["target"]
        key = (target["fault_id"], row["active"], row["tool"])
        if key in seen: raise ValueError("Duplicate execution")
        seen.add(key)
        raw = row["observation"]
        if raw["execution_status"] not in ("CUDA_SUCCESS", "MODEL_SUCCESS"):
            counts[raw["execution_status"]] += 1
            continue
        if (row["backend"], raw["execution_status"]) not in (("cuda", "CUDA_SUCCESS"), ("cpu-model", "MODEL_SUCCESS")):
            raise ValueError("Fabricated backend success")
        words = raw["consumed_words"]
        if len(words) != 19 or words[2] != 16 or any(type(x) is not int or not 0 <= x < 2**32 for x in words):
            raise ValueError("Malformed consumer witness")
        if sum(words[3:]) % 2**32 != raw["consumer_sum"]: raise ValueError("Computation not from consumed bytes")
        observed = {"buffer_id": words[0], "generation": words[1],
                    "payload_tag": hashlib.sha256(struct.pack("<16I", *words[3:])).hexdigest()}
        wanted = {k:target["expected_state"][k] for k in ("buffer_id","generation","payload_tag")}
        verdict = "PASS" if observed == wanted else "STATE_CONTINUITY_VIOLATION"
        if row["B3_CC_Contract"]["classification"] != verdict: raise ValueError("Detector/auditor disagree")
        activated = bool(row["active"] and observed == {k:target["reachable_wrong_state"][k] for k in ("buffer_id","generation","payload_tag")})
        if row["activated"] != activated: raise ValueError("Activation was not observed")
        # Independently regenerate the expected payload from the frozen specification.
        raw_expected = hashlib.shake_256(f"hdsc-evaluation-v1/{target['seed']}/{wanted['buffer_id']}/{wanted['generation']}".encode()).digest(64)
        if hashlib.sha256(raw_expected).hexdigest() != wanted["payload_tag"]: raise ValueError("Changed expected intent")
        expected_sum = sum(struct.unpack("<16I", raw_expected)) % 2**32
        output_verdict = "PASS" if raw["consumer_sum"] == expected_sum else "ALERT"
        if row["B1_output_only"] != output_verdict: raise ValueError("Output-only auditor mismatch")
        status = "PASS" if raw["execution_status"] == "CUDA_SUCCESS" else "UNSUPPORTED"
        if row["B0_cuda_status"] != status: raise ValueError("Status baseline mismatch")
        counts[verdict] += 1
        counts["B1/" + output_verdict] += 1
    return {"state": "PASS_INDEPENDENT_RQ2_AUDIT", "rows": len(rows), "counts": dict(counts),
            "runs_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "detector_and_injector_imported": False,
            "scope": sorted({r["backend"] for r in rows}),
            "reserved_evaluation_present": any(r["target"]["split"] == "reserved_evaluation" for r in rows)}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('runs',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();result=audit(args.runs)
    with args.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result))


if __name__=='__main__':main()
