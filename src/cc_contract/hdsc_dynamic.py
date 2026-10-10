"""Online workload with data-dependent branching and a persistent CUDA worker."""
import argparse
from functools import reduce
import json
import operator
from pathlib import Path
import select
import struct
import subprocess

from .hdsc_benchmark import FAULTS, packets
from .hdsc_runtime import Ledger, State


class Device:
    def __init__(self, backend, worker):
        self.backend = backend
        self.process = None
        if backend == "cuda":
            self.process = subprocess.Popen([str(worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, bufsize=0)
            first = self.read()
            if first != {"ready": True}:
                self.close()
                raise RuntimeError(json.dumps(first))

    def read(self):
        # Byte reads avoid a buffered reader hiding already-read lines from select.
        data = bytearray()
        while not data.endswith(b"\n"):
            if not select.select([self.process.stdout], [], [], 30)[0]:
                raise TimeoutError("CUDA worker response deadline")
            byte = self.process.stdout.read(1)
            if not byte or len(data) > 65536:
                raise RuntimeError("CUDA worker response incomplete")
            data.extend(byte)
        return json.loads(data)

    def step(self, data, fault, active, kernel, single_stream=False):
        if self.process:
            self.process.stdin.write(struct.pack("<4I", FAULTS.index(fault), int(active), kernel, int(single_stream)) + b"".join(data))
            return self.read()
        selected_packet = 2 if active and fault == "C2" else 0 if active else 1
        selected_slot = 2 if selected_packet == 2 else 1 if fault == "L2" and not active else 0
        words = list(struct.unpack("<19I", data[selected_packet]))
        value = (sum(words[3:]) % 2**32) if kernel == 0 else reduce(operator.xor, words[3:], 0)
        return {"execution_status": "MODEL_SUCCESS", "consumed_words": words, "value": value,
                "consumer": kernel + 1, "selected_slot": selected_slot, "selected_packet": selected_packet,
                "waited_epoch": 0 if active and fault in ("L1", "C1") else 1}

    def close(self):
        if self.process:
            process = self.process
            self.process = None
            process.stdin.close()
            process.stdin = None
            try:
                remaining, errors = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
                raise RuntimeError("CUDA worker cleanup deadline")
            finally:
                process.stdout.close(); process.stderr.close()
            if process.returncode or remaining.strip() or errors.strip():
                raise RuntimeError("CUDA worker cleanup failed: " +
                                   (remaining + errors).decode(errors="replace")[:2048])


def run(seed, fault=None, backend="cpu-model", worker="/usr/local/bin/cc-hdsc-dynamic-worker", max_steps=12, pattern="dynamic", observer=None):
    if pattern not in ("dynamic", "single-stream", "multi-stream", "event-dependencies", "double-buffering", "graph-replay", "generation-reuse", "dynamic-branch"):
        raise ValueError("Unknown healthy pattern")
    if fault not in (None, *FAULTS) or not 4 <= max_steps <= 12:
        raise ValueError("Invalid workload parameters")
    ledger = Ledger()
    device = Device(backend, worker)
    rows, generations = [], {1: 1, 2: 1, 3: 1}
    previous = seed
    try:
        for step in range(max_steps):
            # These decisions require the preceding actual consumer result.
            buffer_id = 1 + previous % (2 if pattern == "double-buffering" else 3)
            if pattern in ("single-stream", "generation-reuse", "graph-replay"): buffer_id = 1
            kernel = (previous // 3) % 2
            generation = generations[buffer_id] + 1; generations[buffer_id] = generation
            mode = FAULTS[(previous // 7) % 4] if fault is None else fault
            if pattern == "graph-replay" and fault is None: mode = "L2"
            active = fault is not None and step == 2
            data = packets(seed + step, "changed-output", buffer_id, generation)
            consumer_name = "sum" if kernel == 0 else "xor"
            event = f"step-{step}/new"
            producer_stream = "consumer" if pattern == "single-stream" else "producer"
            expected = ledger.declare(buffer_id, generation, data[1][12:], "application", producer_stream, event, consumer_name)
            observed = device.step(data, mode, active, kernel, pattern == "single-stream")
            if observed.get("execution_status") not in ("MODEL_SUCCESS", "CUDA_SUCCESS"):
                rows.append({"step": step, "observation": observed})
                if observer: observer(rows[-1])
                break
            # Reconstruct executed bindings from actual adapter receipts, not the fault label.
            index = observed["selected_packet"]
            selected_slot = observed["selected_slot"]
            old = State(buffer_id, generation - 1, "application", producer_stream, f"step-{step}/old", consumer_name, "")
            wrong = State(buffer_id + 100, generation, "alternate-producer", producer_stream, f"step-{step}/alternate", consumer_name, "")
            binding = (old, expected, wrong)[index]
            ledger.transferred(selected_slot, binding)
            ledger.recorded(binding.dependency, selected_slot)
            if observed["waited_epoch"] == 1 and binding.dependency != event:
                ledger.transferred("new-snapshot", expected); ledger.recorded(event, "new-snapshot")
            waited = event if observed["waited_epoch"] == 1 else f"step-{step}/old"
            ledger.waited("consumer", waited)
            graph = f"graph-{step}" if mode == "L2" else None
            if graph: ledger.captured(graph, selected_slot)
            selected = ledger.launch(expected, selected_slot, "consumer", graph=graph)
            words = observed["consumed_words"]
            verdict = ledger.complete(expected, selected, "consumer", observed["execution_status"],
                                      struct.pack("<16I", *words[3:]), words[0], words[1],
                                      {1: "sum", 2: "xor"}[observed["consumer"]])
            arithmetic = sum(words[3:]) % 2**32 if kernel == 0 else reduce(operator.xor, words[3:], 0)
            if arithmetic != observed["value"]:
                raise ValueError("Consumer computation does not match consumed bytes")
            rows.append({"step": step, "input_seed": seed + step, "prior_output": previous,
                         "expected": expected.public(), "observation": observed, "verdict": verdict,
                         "injection_requested": active, "fault": mode, "graph": graph})
            if observer: observer(rows[-1])
            previous = observed["value"]
            if step >= 3 and previous % 5 == 0:
                break
    finally:
        device.close()
    return {"seed": seed, "backend": backend, "fault": fault, "steps": rows,
            "pattern": pattern, "trace_known_to_verifier_in_advance": False, "physical_allocation_reuse": backend == "cuda"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=int, default=82000)
    p.add_argument("--fault", choices=FAULTS)
    p.add_argument("--backend", choices=("cpu-model", "cuda"), default="cpu-model")
    p.add_argument("--worker", default="/usr/local/bin/cc-hdsc-dynamic-worker")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = run(args.seed, args.fault, args.backend, args.worker)
    with args.output.open("x") as out: json.dump(result, out, indent=2); out.write("\n")
    print(json.dumps({"steps": len(result["steps"]), "backend": args.backend}))


if __name__ == "__main__":
    main()
