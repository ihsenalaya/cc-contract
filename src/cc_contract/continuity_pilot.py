"""Reproducible serial pilot. This module never starts or provisions a VM."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import struct
import subprocess
import time

from .continuity_model import FAULTS, simulate
from .continuity_oracle import ExpectedState, classify

PROTOCOL = "state-continuity-pilot-v0.1"


def inputs(seed):
    if type(seed) is not int or not 0 <= seed < 2 ** 32:
        raise ValueError("Seed must be uint32")
    packets = []
    for identity, generation in ((1, 1), (1, 2), (2, 2)):
        raw = hashlib.shake_256(f"{PROTOCOL}/{seed}/{identity}/{generation}".encode()).digest(64)
        words = struct.unpack("<16I", raw)
        packets.append(struct.pack("<3I", identity, generation, 16) + raw)
        if (identity, generation) == (1, 2):
            expected = ExpectedState(identity, generation, words)
    return expected, packets


def schedule():
    """Ten fixed blocks, five serial runs each, including one healthy control."""
    rng = random.Random(10102026)
    rows = []
    for block in range(10):
        group = [(fault, True) for fault in FAULTS] + [(FAULTS[block % 4], False)]
        rng.shuffle(group)
        for fault, active in group:
            rows.append(dict(run_id=len(rows), block=block, seed=71000 + block,
                             group=fault if active else "HEALTHY", fault=fault, active=active))
    return rows


def execute(row, backend, worker=None):
    expected, packets = inputs(row["seed"])
    start = time.perf_counter_ns()
    raw_worker = None
    if backend == "cpu-model":
        observation = simulate(packets, row["fault"], row["active"])
    elif backend == "cuda":
        try:
            proc = subprocess.run([str(worker), row["fault"], str(int(row["active"]))],
                                  input=b"".join(packets), capture_output=True, timeout=10)
            raw_worker = dict(stdout=proc.stdout.decode("utf-8", errors="replace"),
                              stderr=proc.stderr.decode("utf-8", errors="replace"),
                              returncode=proc.returncode)
            observation = json.loads(proc.stdout)
            if proc.returncode or not isinstance(observation, dict) or observation.get("backend") != "cuda":
                observation = {"backend": "cuda", "execution_status": "INFRA_FAILURE"}
        except subprocess.TimeoutExpired as error:
            raw_worker = dict(stdout=(error.stdout or b"").decode("utf-8", errors="replace"),
                              stderr=(error.stderr or b"").decode("utf-8", errors="replace"),
                              returncode=None)
            observation = {"backend": "cuda", "execution_status": "INFRA_FAILURE",
                           "reason": "worker_timeout_10_seconds"}
        except (OSError, ValueError, TypeError):
            observation = {"backend": "cuda", "execution_status": "INFRA_FAILURE",
                           "reason": "worker_or_protocol_failure"}
    else:
        raise ValueError("Unsupported backend")
    execution_ns = time.perf_counter_ns() - start
    detect_start = time.perf_counter_ns()
    verdict = classify(expected, observation)
    detection_ns = time.perf_counter_ns() - detect_start
    # Activation is assessed AFTER detection from the actual observed state.
    # A requested injection is never counted as activation merely by request.
    observed = verdict.get("observed_state", {})
    success = observation.get("execution_status") in ("MODEL_SUCCESS", "CUDA_SUCCESS")
    signature = (observed.get("observed_buffer_id"), observed.get("observed_generation"))
    activation = bool(row["active"] and success and signature ==
                      ((2, 2) if row["fault"] == "C2" else (1, 1)))
    return dict(**row, backend=backend, expected_state=expected.public(),
                observation=observation, verdict=verdict, activated=activation,
                raw_worker=raw_worker,
                execution_ns=execution_ns, detection_ns=detection_ns,
                detector_host_fraction=detection_ns / max(execution_ns, 1),
                instrumentation_overhead=None)


def summarize(rows):
    table = []
    for group in ("HEALTHY", *FAULTS):
        runs = [r for r in rows if r["group"] == group]
        counts = Counter(r["verdict"]["classification"] for r in runs)
        detected = sum(r["activated"] and r["verdict"]["classification"] ==
                       "STATE_CONTINUITY_VIOLATION" for r in runs)
        activated = sum(r["activated"] for r in runs)
        table.append(dict(fault=group, runs=len(runs), activated=activated,
                          cuda_success=sum(r["observation"]["execution_status"] == "CUDA_SUCCESS" for r in runs),
                          model_success=sum(r["observation"]["execution_status"] == "MODEL_SUCCESS" for r in runs),
                          detected=detected, missed=activated - detected,
                          not_activated=sum(r["active"] and not r["activated"] for r in runs),
                          false_positives=counts["STATE_CONTINUITY_VIOLATION"] if group == "HEALTHY" else None,
                          classifications=dict(counts)))
    return table


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("cpu-model", "cuda"), default="cpu-model")
    parser.add_argument("--worker", default="/usr/local/bin/cc-continuity-worker")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    rows = []
    for row in schedule():
        result = execute(row, args.backend, args.worker)
        rows.append(result)
        with (args.output / "runs.jsonl").open("a") as stream:
            stream.write(json.dumps(result, sort_keys=True) + "\n")
        print(json.dumps({"run": row["run_id"], "group": row["group"],
                          "classification": result["verdict"]["classification"]}), flush=True)
        if result["verdict"]["classification"] not in ("PASS", "STATE_CONTINUITY_VIOLATION"):
            break  # stop on technical errors; never repair with paid compute running
    summary = dict(protocol=PROTOCOL, backend=args.backend, planned_runs=50, actual_runs=len(rows),
                   completed_utc=datetime.now(timezone.utc).isoformat(),
                   wall_seconds=time.perf_counter() - started, metrics=summarize(rows),
                   runs_sha256=hashlib.sha256((args.output / "runs.jsonl").read_bytes()).hexdigest(),
                   real_cuda_validated=args.backend == "cuda" and len(rows) == 50 and
                       all(r["observation"]["execution_status"] == "CUDA_SUCCESS" for r in rows),
                   instrumentation_overhead="NOT_MEASURED_REQUIRES_UNINSTRUMENTED_CONTROL",
                   oracle_scope="instrumented_consumer_not_cryptographic_attestation")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if len(rows) != 50:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
