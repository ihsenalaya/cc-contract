"""Serial RQ2 runner, CPU development only unless explicitly selecting CUDA."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time

from .continuity_model import simulate
from .continuity_oracle import ExpectedState, classify
from .hdsc_benchmark import packets, schedule, state
from .hdsc_baselines import cuda_status, output_only, sanitizer_command, sanitizer_result


def execute(row, backend, worker):
    target = row["target"]
    expected_info = target["expected_state"]
    data = packets(target["seed"], target["state_variant"], expected_info["buffer_id"], expected_info["generation"])
    assert [hashlib.sha256(p).hexdigest() for p in data] == target["packet_sha256"]
    expected = ExpectedState(expected_info["buffer_id"], expected_info["generation"], struct.unpack("<16I", data[1][12:]))
    start = time.perf_counter_ns()
    raw = None
    sanitizer = {"classification": "NOT_RUN"}
    if backend == "cpu-model":
        if row["tool"] != "direct" or target["split"] != "development":
            raise ValueError("CPU qualification must not execute reserved evaluations or simulate a sanitizer")
        observation = simulate(data, target["fault_class"], row["active"])
    elif backend == "cuda":
        cmd = ([str(worker), target["fault_class"], str(int(row["active"]))] if row["tool"] == "direct" else
               sanitizer_command(row["tool"], worker, target["fault_class"], row["active"]))
        try:
            proc = subprocess.run(cmd, input=b"".join(data), capture_output=True, timeout=30)
            stdout, stderr = proc.stdout.decode(errors="replace"), proc.stderr.decode(errors="replace")
            raw = dict(stdout=stdout, stderr=stderr, returncode=proc.returncode, command=cmd)
            observations = [json.loads(line) for line in stdout.splitlines() if line.startswith('{"backend"')]
            observation = observations[0] if len(observations) == 1 else {"execution_status": "INFRA_FAILURE"}
            if row["tool"] != "direct":
                sanitizer = sanitizer_result(row["tool"], proc.returncode, stdout, stderr, observation)
            elif proc.returncode:
                observation = {"execution_status": "INFRA_FAILURE"}
        except subprocess.TimeoutExpired as error:
            raw = {"command": cmd, "timeout": True, "stdout": (error.stdout or b"").decode(errors="replace"),
                   "stderr": (error.stderr or b"").decode(errors="replace")}
            observation = {"execution_status": "INFRA_FAILURE"}
        except (OSError, ValueError):
            observation = {"execution_status": "INFRA_FAILURE"}
    else:
        raise ValueError("Unknown backend")
    elapsed = time.perf_counter_ns() - start
    verdict = classify(expected, observation)
    words = observation.get("consumed_words")
    actual = state(struct.pack("<19I", *words)) if words and len(words) == 19 else None
    activation = bool(row["active"] and observation.get("execution_status") in ("MODEL_SUCCESS", "CUDA_SUCCESS")
                      and actual == {k:target["reachable_wrong_state"][k] for k in ("buffer_id","generation","payload_tag")})
    output = output_only(sum(expected.payload) % 2**32, observation.get("consumer_sum"))
    return {**row, "backend": backend, "observation": observation, "raw_worker": raw,
            "activated": activation, "B0_cuda_status": cuda_status(observation),
            "B1_output_only": output, "B2_sanitizer": sanitizer, "B3_CC_Contract": verdict,
            "execution_ns": elapsed, "CUDA_status_simulated": False,
            "verified_projection": ["buffer_id", "generation", "payload_tag"],
            "RQ2_worker_attribution_limit": "producer/stream/dependency/consumer are protocol context, not independently observed by this worker"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", choices=("cpu-model", "cuda"), default="cpu-model")
    p.add_argument("--split", choices=("development", "reserved_evaluation"), default="development")
    p.add_argument("--worker", default="/usr/local/bin/cc-continuity-worker")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows = schedule(args.split)
    if args.backend == "cpu-model":
        rows = [r for r in rows if r["tool"] == "direct"]
    results = []
    with (args.output / "runs.jsonl").open("x") as out:
        for row in rows:
            result = execute(row, args.backend, args.worker)
            out.write(json.dumps(result, sort_keys=True) + "\n"); out.flush()
            results.append(result)
            if result["B3_CC_Contract"]["classification"] not in ("PASS", "STATE_CONTINUITY_VIOLATION"):
                break
            if result["B2_sanitizer"]["classification"] == "INFRA_FAILURE":
                break
    summary = {"scope": "CPU_DEVELOPMENT_ONLY" if args.backend == "cpu-model" else "REAL_CUDA_RQ2",
               "planned_runs": len(rows), "actual_runs": len(results),
               "CC_Contract": dict(Counter(x["B3_CC_Contract"]["classification"] for x in results)),
               "output_only": dict(Counter(x["B1_output_only"] for x in results)),
               "cuda_status": dict(Counter(x["B0_cuda_status"] for x in results)),
               "runs_sha256": hashlib.sha256((args.output / "runs.jsonl").read_bytes()).hexdigest(),
               "reserved_evaluation_executed": args.split == "reserved_evaluation"}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))
    if len(results) != len(rows):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
