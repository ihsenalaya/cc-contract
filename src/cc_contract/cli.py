"""Provenance-preserving local runner. No CUDA/attestation claims."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4
from .contracts import InvalidScenario, UnsupportedScenario, validate
from .corpus import initial_corpus
from .model import execute


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def provenance() -> tuple[str, bool | None]:
    pinned = os.environ.get("CC_COMMIT")
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
        tree = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    except FileNotFoundError:
        if not pinned:
            raise RuntimeError("Git absent and no build commit supplied")
        return pinned, None
    commit = pinned or (proc.stdout.strip() if proc.returncode == 0 else "UNCOMMITTED")
    dirty = bool(tree.stdout.strip()) if tree.returncode == 0 else None
    return commit, dirty


def run_case(entry: dict) -> dict:
    started = time.monotonic()
    observations, reason = [], None
    try:
        validate(entry["scenario"])
        observations = execute(entry["scenario"], entry["mutation"])
        verdict = "FAIL" if any(o["verdict"] == "FAIL" for o in observations) else "PASS"
    except InvalidScenario as error:
        verdict, reason = "INVALID_TEST", str(error)
    except UnsupportedScenario as error:
        verdict, reason = "UNSUPPORTED", str(error)
    return {**entry, "verdict": verdict, "reason": reason, "observations": observations, "duration_seconds": time.monotonic() - started, "matches_expectation": verdict == entry["expected_verdict"], "scope": "CPU_SIMULATION_ONLY", "gpu_executed": False, "hardware_attestation": "NOT_RUN"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["corpus", "selftest"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--emit-records", action="store_true")
    args = parser.parse_args()
    if args.command == "corpus":
        print(json.dumps(initial_corpus(), indent=2))
        return 0
    timestamp = datetime.now(timezone.utc).isoformat()
    run_id = "local-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    records = [dict(run_id=run_id, timestamp_utc=timestamp, **run_case(entry)) for entry in initial_corpus()]
    commit, dirty = provenance()
    source = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        source.update(path.name.encode())
        source.update(path.read_bytes())
    ok = all(r["matches_expectation"] for r in records)
    raw = b"".join(canonical(r) for r in records)
    manifest = {"schema_version": 1, "run_id": run_id, "timestamp_utc": timestamp, "experiment": "E1_INITIAL_MODEL_QUALIFICATION", "scope": "CPU_SIMULATION_ONLY", "git_commit": commit, "working_tree_dirty": dirty, "source_sha256": source.hexdigest(), "image_digest": os.environ.get("CC_IMAGE_DIGEST", "NOT_APPLICABLE_LOCAL_PROCESS"), "build_image_id": os.environ.get("CC_BUILD_IMAGE_ID"), "environment": {"python": platform.python_version(), "platform": platform.platform()}, "seed_policy": "recorded_per_case_0_to_23", "budget": {"cases": 60, "maximum_integer_buffer_size": 65536}, "counts": {v: sum(r["verdict"] == v for r in records) for v in ["PASS", "FAIL", "INVALID_TEST", "UNSUPPORTED"]}, "expectations_matched": sum(r["matches_expectation"] for r in records), "state": "COMPLETE_LOCAL_MODEL_CHECK" if ok else "FAILED_LOCAL_MODEL_CHECK", "gpu_executed": False, "hardware_attestation": "NOT_RUN", "controlled_mutants_are_real_discoveries": False, "raw_file": "records.jsonl", "raw_sha256": hashlib.sha256(raw).hexdigest(), "corpus_sha256": hashlib.sha256(canonical(initial_corpus())).hexdigest()}
    if args.output:
        directory = args.output / run_id
        directory.mkdir(parents=True, exist_ok=False)
        raw_path = directory / "records.jsonl"
        raw_path.write_bytes(raw)
        manifest_path = directory / "manifest.json"
        manifest_path.write_bytes(canonical(manifest))
        raw_path.chmod(0o444)
        manifest_path.chmod(0o444)
    if args.emit_records:
        for record in records:
            print(canonical(dict(record_type="case", **record)).decode(), end="")
        print(canonical(dict(record_type="manifest", **manifest)).decode(), end="")
    else:
        print(json.dumps(manifest, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
