"""Verify exported CPU records, expected verdicts and integrity."""
import hashlib
import json
from pathlib import Path
import sys
from cc_contract.cli import canonical


def verify(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    manifests = [r for r in rows if r.get("record_type") == "manifest"]
    records = [r for r in rows if r.get("record_type") == "case"]
    if len(manifests) != 1 or len(records) != 60:
        raise ValueError("must contain exactly one manifest and 60 records")
    manifest = manifests[0]
    clean = [{k: v for k, v in r.items() if k != "record_type"} for r in records]
    raw_hash = hashlib.sha256(b"".join(canonical(r) for r in clean)).hexdigest()
    if raw_hash != manifest["raw_sha256"]:
        raise ValueError("raw record hash mismatch")
    if any(r["run_id"] != manifest["run_id"] or r["scope"] != "CPU_SIMULATION_ONLY" or r["gpu_executed"] or not r["matches_expectation"] for r in records):
        raise ValueError("provenance/scope/expected verdict mismatch")
    counts = {v: sum(r["verdict"] == v for r in records) for v in ["PASS", "FAIL", "INVALID_TEST", "UNSUPPORTED"]}
    if counts != manifest["counts"] or counts != {"PASS": 24, "FAIL": 24, "INVALID_TEST": 12, "UNSUPPORTED": 0}:
        raise ValueError("category count mismatch")
    if len({r["scenario"]["id"] for r in records}) != 60:
        raise ValueError("duplicate scenario IDs")
    return manifest


if __name__ == "__main__":
    m = verify(Path(sys.argv[1]))
    print(json.dumps({"run_id": m["run_id"], "verified": True, "counts": m["counts"], "raw_sha256": m["raw_sha256"]}))
