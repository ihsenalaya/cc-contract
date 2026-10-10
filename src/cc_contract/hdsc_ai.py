"""Trained TinyStories Transformer boundary, dynamic host dispatch and CUDA Graphs.

The ON path feeds the model from the exact snapshot returned to the verifier.
The OFF path has no snapshot, state header or verifier. Model weights are never
downloaded by this workload; callers supply hash-verified offline assets.
"""
import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import random
import struct
import time

from .hdsc_runtime import Ledger, State
from .hdsc_statistics import percentile, paired_effect

PROMPTS = ("Once upon a time there was a little girl", "The dog and the cat went to the park",
           "One day a boy found a small red ball", "The sun was bright and the bird could sing")
EVALUATION_PROMPTS = (
    "A rabbit carried a basket of apples to the village",
    "Mia opened the blue door and saw a friendly bear",
    "The little boat floated across the quiet lake",
    "Sam wanted to bake a cake for his sister",
    "A fox found a yellow hat beside the old tree",
    "The children planted a seed in the garden",
    "A small dragon learned to share its toys",
    "The puppy waited patiently beside the window",
    "Lily and her grandfather walked to the river",
    "A green frog heard a song coming from the forest")
HEALTHY_PROMPTS = (
    "The farmer gave the thirsty horse a drink",
    "A kitten fell asleep inside a warm basket",
    "Tom put on his boots before going outside",
    "The owl watched the moon rise over the hill",
    "A little mouse invited its friends to dinner",
    "Ella found a smooth stone near the waterfall",
    "The duck followed its mother around the pond",
    "A happy squirrel collected nuts for the winter",
    "Ben and his father repaired the wooden fence",
    "The butterfly landed gently on a purple flower")


def prompt_for_seed(seed):
    if 82000 <= seed < 82008: return PROMPTS[(seed-82000) % len(PROMPTS)]
    if 93000 <= seed < 93010: return EVALUATION_PROMPTS[seed-93000]
    if 104000 <= seed < 104010: return HEALTHY_PROMPTS[seed-104000]
    raise ValueError("Seed outside versioned AI input splits")


def token_bytes(values):
    return struct.pack("<" + "q" * len(values), *values)


def verify_assets(directory):
    manifest = json.loads((directory / "artifact-manifest.json").read_text())
    if manifest["model"] != "roneneldan/TinyStories-1M" or manifest["revision"] != "77f1b168e219585646439073245fe87e56b3023e":
        raise ValueError("Unqualified model identity")
    for name, info in manifest["files"].items():
        if Path(name).name != name or hashlib.sha256((directory / name).read_bytes()).hexdigest() != info["sha256"]:
            raise ValueError("Model artifact hash mismatch")
    return manifest


class Transformer:
    def __init__(self, directory, device="cpu", enabled=True):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.assets = verify_assets(Path(directory))
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("UNSUPPORTED: no CUDA device")
        self.torch, self.device, self.enabled = torch, device, enabled
        torch.set_num_threads(1)
        torch.manual_seed(711031)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        self.model = AutoModelForCausalLM.from_pretrained(directory, local_files_only=True,
                         trust_remote_code=False, weights_only=True, attn_implementation="eager").eval().to(device)
        from .hdsc_graph_attention import install
        self.graph_attention_adapter = install(self.model)
        self.tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True, trust_remote_code=False)
        self.buffers = [torch.zeros(19 if enabled else 16, dtype=torch.long, device=device) for _ in range(3)]
        self.graphs, self.outputs, self.snapshots = [], [], []
        self.producer = torch.cuda.Stream() if device == "cuda" else None
        self.consumer = torch.cuda.Stream() if device == "cuda" else None
        if device == "cuda":
            # Model and initialized buffers are ready before side-stream warmup.
            self.producer.wait_stream(torch.cuda.current_stream())
            self.consumer.wait_stream(torch.cuda.current_stream())
            with torch.inference_mode(), torch.cuda.stream(self.consumer):
                for buf in self.buffers:
                    for _ in range(3): self.compute(buf)
                self.consumer.synchronize()
                for buf in self.buffers:
                    graph = torch.cuda.CUDAGraph()
                    with torch.cuda.graph(graph, stream=self.consumer):
                        logits, snapshot = self.compute(buf)
                    self.graphs.append(graph); self.outputs.append(logits); self.snapshots.append(snapshot)
            self.consumer.synchronize()

    def compute(self, buffer):
        snapshot = buffer.clone() if self.enabled else None
        tokens = snapshot[3:] if self.enabled else buffer
        logits = self.model(tokens.unsqueeze(0), use_cache=False).logits[0, -1]
        return logits, snapshot

    def synchronize(self):
        if self.device == "cuda": self.torch.cuda.synchronize()

    def request(self, seed, fault=None, max_steps=8, inject=True, capture_logits=True):
        if fault not in (None, "L1", "L2", "C1", "C2") or max_steps not in (4, 8):
            raise ValueError("Unfrozen AI request")
        torch = self.torch
        initial = self.tokenizer.encode(prompt_for_seed(seed))[-16:]
        tokens = ([self.tokenizer.eos_token_id] * (16 - len(initial))) + initial
        alternate = list(reversed(tokens))
        ledger, rows, outputs = Ledger(), [], []
        old_tokens = tokens.copy()
        verifier_ns = copies = synchronizations = 0
        first_token_ns = None
        self.synchronize()
        if self.device == "cuda":
            start_event, end_event = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            start_event.record(self.consumer)
        started = time.perf_counter_ns()
        with torch.inference_mode():
            for step in range(max_steps):
                generation = step + 2
                # Actual preceding token, not a pre-recorded execution sequence.
                graph_path = step == 2 if fault == "L2" else (tokens[-1] % 2 == 0)
                active = inject and fault is not None and step == 2
                consumer_name = "transformer-graph" if graph_path else "transformer-eager"
                event = f"inference-{step}/ready"
                payload = token_bytes(tokens)
                expected = (ledger.declare(1, generation, payload, "tokenizer-or-prior-logit", "producer", event, consumer_name)
                            if self.enabled else None)
                # Three live allocations distinguish stale snapshot from in-place reuse.
                slot_values = [(1, generation - 1, old_tokens), (1, generation, tokens), (2, generation, alternate)]
                context = torch.cuda.stream(self.producer) if self.device == "cuda" else nullcontext()
                with context:
                    for index, (identity, version, value) in enumerate(slot_values):
                        vals = [identity, version, 16, *value] if self.enabled else value
                        self.buffers[index].copy_(torch.tensor(vals, dtype=torch.long, device="cpu"), non_blocking=False)
                    published = [0, 1, 2]
                    if fault in ("L1", "C1") and not active:
                        self.buffers[0].copy_(self.buffers[1]); published[0] = 1
                    if self.device == "cuda":
                        ready = torch.cuda.Event(); ready.record(self.producer)
                # L1 is a forced late producer: consume old slot before intended publication.
                # C1 omits publication; L2 replays a graph retaining the old input address.
                # Both old/new allocations remain alive; no racy write during inference.
                selected = 2 if active and fault == "C2" else 0 if active or fault in ("L1", "C1") else 1
                if self.device == "cuda": self.consumer.wait_event(ready)
                with torch.cuda.stream(self.consumer) if self.device == "cuda" else nullcontext():
                    if graph_path and self.device == "cuda":
                        self.graphs[selected].replay()
                        logits, snapshot = self.outputs[selected], self.snapshots[selected]
                    else:
                        logits, snapshot = self.compute(self.buffers[selected])
                    next_token = int(logits.argmax().item())
                    output_logits = logits.detach().cpu().tolist() if capture_logits else None
                    observed_words = snapshot.detach().cpu().tolist() if self.enabled else None
                synchronizations += 1  # Required data-dependent host branch in both modes.
                if first_token_ns is None: first_token_ns = time.perf_counter_ns() - started
                verdict = None
                if self.enabled:
                    detect_start = time.perf_counter_ns()
                    packet_index = published[selected]
                    identity, version, _ = slot_values[packet_index]
                    actual_event = event if packet_index == 1 else f"inference-{step}/old-{packet_index}"
                    binding = State(identity, version, "tokenizer-or-prior-logit", "producer", actual_event, consumer_name,
                                    hashlib.sha256(token_bytes(slot_values[packet_index][2])).hexdigest())
                    ledger.transferred(selected, binding); ledger.recorded(actual_event, selected); ledger.waited("consumer", actual_event)
                    chosen = ledger.launch(expected, selected, "consumer")
                    verdict = ledger.complete(expected, chosen, "consumer", "CUDA_SUCCESS" if self.device == "cuda" else "MODEL_SUCCESS",
                        token_bytes(observed_words[3:]), observed_words[0], observed_words[1], consumer_name)
                    verdict["attribution"]["device_observed"].remove("consumer")
                    verdict["attribution"]["trusted_API_adapter"].append("consumer")
                    verifier_ns += time.perf_counter_ns() - detect_start
                    copies += 2  # Device snapshot and witness D2H; payload preparation is inside total wall time.
                if active and fault == "L1":
                    with torch.cuda.stream(self.producer) if self.device == "cuda" else nullcontext():
                        self.buffers[0].copy_(self.buffers[1])
                    self.synchronize()  # Late publication after the completed consumer, never a race.
                rows.append({"step": step, "generation": generation, "graph_path": graph_path,
                             "snapshot_words": observed_words, "verdict": verdict,
                             "execution_status": "CUDA_SUCCESS" if self.device == "cuda" else "MODEL_SUCCESS",
                             "injection_requested": active, "fault": fault, "next_token": next_token,
                             "logits": output_logits})
                outputs.append(next_token)
                old_tokens = tokens.copy(); tokens = tokens[1:] + [next_token]
                if step >= 3 and next_token % 5 == 0: break
        if self.device == "cuda":
            end_event.record(self.consumer); end_event.synchronize()
            gpu_ms = start_event.elapsed_time(end_event)
        else: gpu_ms = None
        self.synchronize()
        wall_ns = time.perf_counter_ns() - started
        return {"backend": self.device, "enabled": self.enabled, "seed": seed, "fault": fault,
                "graph_attention_adapter": self.graph_attention_adapter,
                "tokens": outputs, "steps": rows, "wall_ns": wall_ns, "TTFT_ns": first_token_ns,
                "GPU_stream_interval_ms": gpu_ms, "CPU_verifier_ns": verifier_ns,
                "extra_copies": copies, "required_branch_syncs": synchronizations,
                "witness_D2H_sync_points": len(rows) if self.enabled else 0,
                "persistent_input_bytes": sum(x.numel()*x.element_size() for x in self.buffers),
                "GPU_max_allocated_bytes": torch.cuda.max_memory_allocated() if self.device == "cuda" else None,
                "instrumentation_boundary": "input snapshot actually passed to model; consumer name from trusted adapter"}


def performance(directory, device, seed, warmups=3, repetitions=10):
    records = []
    order = [False, True]; random.Random(seed).shuffle(order)
    for enabled in order:
        model = Transformer(directory, device, enabled)
        for _ in range(warmups): model.request(seed, capture_logits=False)
        if device == "cuda": model.torch.cuda.reset_peak_memory_stats()
        samples = [model.request(seed, capture_logits=False) for _ in range(repetitions)]
        durations = [r["wall_ns"] / 1e6 for r in samples]
        records.append({"mode": "CC_CONTRACT_ON" if enabled else "BASELINE_OFF", "seed": seed,
                        "warmups": warmups, "measured_requests": repetitions,
                        "latency_p50_ms": percentile(durations, .5), "latency_p95_ms": percentile(durations, .95),
                        "throughput_requests_per_s": repetitions / (sum(durations) / 1000),
                        "tokens_per_s": sum(len(r["tokens"]) for r in samples) / (sum(durations)/1000),
                        "samples": samples})
        del model
        if device == "cuda":
            import gc, torch
            gc.collect(); torch.cuda.empty_cache()
    by_mode = {r["mode"]:r for r in records}
    off, on = by_mode["BASELINE_OFF"], by_mode["CC_CONTRACT_ON"]
    if [r["tokens"] for r in off["samples"]] != [r["tokens"] for r in on["samples"]]:
        raise ValueError("ON/OFF workload outputs or dynamic paths differ")
    return {"scope": "CPU_HARNESS_CHECK_ONLY" if device == "cpu" else "REAL_GPU_PERFORMANCE_BLOCK",
            "records": records, "overhead_percent": 100*(on["latency_p50_ms"]-off["latency_p50_ms"])/off["latency_p50_ms"],
            "not_a_CC_on_off_hardware_comparison": True}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--device",choices=("cpu","cuda"),default="cpu")
    p.add_argument("--seed",type=int,default=82000);p.add_argument("--fault",choices=("L1","L2","C1","C2"))
    p.add_argument("--performance",action="store_true")
    args=p.parse_args()
    result=(performance(args.model,args.device,args.seed) if args.performance else Transformer(args.model,args.device).request(args.seed,args.fault))
    with args.output.open("x") as out:json.dump(result,out);out.write("\n")
    print(json.dumps({"device":args.device,"performance":args.performance,"output":str(args.output)}))


if __name__=="__main__": main()
