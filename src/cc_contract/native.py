"""Persistent native executor; validation precedes every CUDA operation."""
import json
import os
from queue import Queue, Empty
import subprocess
from threading import Thread
from .contracts import validate, UnsupportedScenario


class InfrastructureFailure(RuntimeError):
    pass


def protocol(scenario):
    validate(scenario)
    result = ["BEGIN"]
    for op in scenario["operations"]:
        kind = op["op"]
        if kind == "alloc":
            result.append(f"ALLOC {op['buffer']} {op['location']} {op['size']} {op.get('memory','pinned')}")
        elif kind == "write":
            result.append(f"WRITE {op['buffer']} {op['generation']} {len(op['values'])} " + " ".join(map(str,op["values"])))
        elif kind in {"copy", "mapped_copy"}:
            result.append(f"{'COPY' if kind=='copy' else 'MAPPED'} {op['source']} {op['target']} {op['stream']}")
        elif kind == "record_event":
            result.append(f"EVENT {op['event']} {op['stream']}")
        elif kind == "wait_event":
            result.append(f"WAIT {op['stream']} {op['event']}")
        elif kind == "sync":
            result.append(f"SYNC {op['stream']}")
        elif kind == "define_graph":
            result.append(f"GRAPH {op['graph']} {op['stream']} {len(op['operations'])}")
            result.extend(f"COPY {o['source']} {o['target']} {o['stream']}" for o in op["operations"])
        elif kind == "replay_graph":
            result.append(f"REPLAY {op['graph']} {op['repeats']}")
        elif kind == "destroy_graph":
            result.append(f"DESTROY_GRAPH {op['graph']}")
        elif kind == "observe":
            result.append(f"OBSERVE {op['buffer']}")
        elif kind == "free":
            result.append(f"FREE {op['buffer']}")
    return "\n".join(result + ["END", ""])


class NativeExecutor:
    def __init__(self, reference=False, capabilities=None, binary=None, timeout=60):
        self.reference, self.timeout = reference, timeout
        self.capabilities = capabilities or ({"mapped":True,"graphs":True} if reference else {})
        self.lines, self.errors = Queue(), []
        args = [binary or os.environ.get("CC_NATIVE_BINARY", "/usr/local/bin/cc-ir-worker")]
        if reference:
            args.append("--cpu-reference")
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        def read_output():
            for line in self.process.stdout:
                self.lines.put(line)
            self.lines.put(None)
        def read_errors():
            for line in self.process.stderr:
                self.errors.append(line)
        Thread(target=read_output,daemon=True).start()
        Thread(target=read_errors,daemon=True).start()
        self.environment = self.next_record()
        if self.environment.get("verdict") == "UNSUPPORTED":
            self.close()
            raise UnsupportedScenario("C0: native CUDA worker has no usable device")
        if self.environment.get("gpu_executed") is reference:
            self.close()
            raise InfrastructureFailure("Native execution scope contradicts selected mode")
        if not reference and capabilities is None:
            try:
                for feature in ('mapped','graphs'):
                    probe = subprocess.run([args[0],'--probe',feature],capture_output=True,text=True,timeout=timeout)
                    record = json.loads(probe.stdout)
                    if probe.returncode==0 and record.get('verdict')=='PASS' and record.get('gpu_executed') is True:
                        self.capabilities[feature]=True
                    elif probe.returncode==77 and record.get('verdict')=='UNSUPPORTED':
                        self.capabilities[feature]=False
                    else:
                        raise InfrastructureFailure('Capability probe failed: '+probe.stderr[-4096:])
            except BaseException:
                self.close()
                raise

    def next_record(self):
        try:
            line = self.lines.get(timeout=self.timeout)
        except Empty as error:
            self.process.kill()
            raise InfrastructureFailure("Native worker timeout") from error
        if line is None:
            raise InfrastructureFailure("Native worker ended: " + "".join(self.errors)[-4096:])
        return json.loads(line)

    def execute(self, scenario, mutation=None):
        validate(scenario)
        if scenario["family"] == "T07" and not self.capabilities.get("mapped"):
            raise UnsupportedScenario("C0: mapped memory not hardware-qualified")
        if scenario["family"] == "T08" and not self.capabilities.get("graphs"):
            raise UnsupportedScenario("C0: graph replay not hardware-qualified")
        if mutation is not None:
            raise ValueError("Native main campaign does not inject semantic mutants")
        # The output reader drains stdout while this writer sends large payloads.
        # Keeping writes off this thread also makes a blocked stdin time out.
        write_errors = []
        def send():
            try:
                self.process.stdin.write(protocol(scenario))
                self.process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as error:
                write_errors.append(error)
        writer = Thread(target=send, daemon=True)
        writer.start()
        expected = [o for o in scenario["operations"] if o["op"] == "observe"]
        observed = []
        while True:
            record = self.next_record()
            if record["record_type"] == "result":
                if record["verdict"] != "COMPLETE":
                    raise InfrastructureFailure("Native execution failed: " + "".join(self.errors)[-4096:])
                break
            observed.append(record)
        writer.join(timeout=self.timeout)
        if writer.is_alive() or write_errors:
            self.process.kill()
            raise InfrastructureFailure("Native input transfer failed")
        if len(expected) != len(observed):
            raise InfrastructureFailure("Native observation count mismatch")
        result = []
        for exp, actual in zip(expected,observed):
            if actual["buffer"] != exp["buffer"] or len(actual["values"]) != len(exp["expected"]):
                raise InfrastructureFailure("Native observation identity/shape mismatch")
            good = actual["values"] == exp["expected"] and actual["generation"] == exp["generation"]
            result.append({"buffer":exp["buffer"],"expected":{"values":exp["expected"],"generation":exp["generation"]},"observed":{"values":actual["values"],"generation":actual["generation"]},"verdict":"PASS" if good else "FAIL","reason":"exact_payload_and_physically_copied_generation","scope":self.environment["scope"],"gpu_executed":not self.reference})
        return result

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdout.close()
        self.process.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()
