"""Qualify 140 serial finite-work jobs on each of two existing Kind CPU workers.

The workers may run concurrently; each has one main-thread native-reference
executor. Existing immutable image bytes are reused. Original partial evidence
is collected before the dedicated namespace is removed. No GPU is accessed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
NODES = ("cc-contract-worker", "cc-contract-worker2")
SELECTED = 4
DEADLINE = 1200

# Binary evidence is transferred directly from a live pod; Kubernetes logs
# contain only a small ready receipt, so log rotation cannot truncate the TAR.
PACKER = r'''import hashlib,json,os,signal,subprocess,sys,tarfile,time
child=None
interrupted=False
def stop(*_):
    global interrupted
    interrupted=True
    if child is not None and child.poll() is None: child.terminate()
signal.signal(signal.SIGTERM,stop)
signal.signal(signal.SIGINT,stop)
with open('/evidence/harness.stdout','wb') as stdout,open('/evidence/harness.stderr','wb') as stderr:
    child=subprocess.Popen(sys.argv[1:],stdout=stdout,stderr=stderr)
    if interrupted: child.terminate()
    try: code=child.wait(timeout=1100)
    except subprocess.TimeoutExpired:
        child.terminate()
        try: child.wait(timeout=15)
        except subprocess.TimeoutExpired: child.kill();child.wait()
        code=124
archive_path='/evidence/worker-evidence.tar.gz'
excluded={'evidence/worker-evidence.tar.gz','evidence/export-ready.json','evidence/export-confirmed'}
with tarfile.open(archive_path,mode='w:gz',compresslevel=1) as archive:
    archive.add('/evidence',arcname='evidence',filter=lambda member:None if member.name in excluded else member)
digest=hashlib.sha256()
with open(archive_path,'rb') as original:
    os.fsync(original.fileno())
    for block in iter(lambda:original.read(8*1024*1024),b''):digest.update(block)
ready={'archive_sha256':digest.hexdigest(),'archive_bytes':os.path.getsize(archive_path),
       'original_returncode':code,'interrupted_before_export':interrupted}
with open('/evidence/export-ready.json','x') as receipt:
    json.dump(ready,receipt);receipt.flush();os.fsync(receipt.fileno())
print(json.dumps(ready),flush=True)
while not os.path.exists('/evidence/export-confirmed'):time.sleep(.25)
sys.exit(code if code else 130 if interrupted else 0)
'''


def command(args, **kwargs):
    kwargs.setdefault("timeout", 90)
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path, value):
    with path.open("x") as output:
        json.dump(value, output, indent=2)
        output.write("\n")


def pod_document(namespace, index, image, spec_hash):
    container = {"name": "campaign", "image": image, "imagePullPolicy": "Never",
        "command": ["python3", "-c", PACKER, "python3", "/inputs/run-fixed-work-campaign.py",
                    "--spec", "/inputs/spec.json", "--spec-sha256", spec_hash,
                    "--output", "/evidence/runs", "--backend", "native-reference",
                    "--selected-case-target", str(SELECTED), "--safety-timeout-seconds", "120",
                    "--helper-script", "/inputs/run-work-sample.py"],
        "env": [{"name": "CC_IMAGE_DIGEST", "value": image}],
        "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                      "limits": {"cpu": "2", "memory": "2Gi"}},
        "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"]}},
        "volumeMounts": [{"name": "inputs", "mountPath": "/inputs", "readOnly": True},
                         {"name": "evidence", "mountPath": "/evidence"}]}
    return {"apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": "campaign-" + str(index), "namespace": namespace},
        "spec": {"backoffLimit": 0, "activeDeadlineSeconds": DEADLINE, "parallelism": 1, "completions": 1,
            "template": {"spec": {"restartPolicy": "Never", "serviceAccountName": "runner",
                "automountServiceAccountToken": False, "terminationGracePeriodSeconds": 60,
                "nodeSelector": {"kubernetes.io/hostname": NODES[index]},
                "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
                    "fsGroup": 10001, "seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [container], "volumes": [{"name": "inputs", "configMap": {"name": "campaign-inputs"}},
                    {"name": "evidence", "emptyDir": {"sizeLimit": "2Gi"}}]}}}}


def archive_inventory(path):
    hashes, captured, names = {}, {}, set()
    wanted = {"evidence/runs/receipt.json": 8 * 1024 * 1024,
              "evidence/runs/spec.json": 2 * 1024 * 1024,
              "evidence/runs/journal.jsonl": 16 * 1024 * 1024}
    with tarfile.open(path, mode="r|gz") as archive:
        for member in archive:
            name = member.name.rstrip("/") if member.isdir() else member.name
            pure = PurePosixPath(name)
            if (len(names) >= 10000 or name in names or len(name.encode()) > 4096 or
                pure.is_absolute() or not pure.parts or pure.parts[0] != "evidence" or
                "\\" in name or any(part in ("", ".", "..") for part in name.split("/")) or
                any(ord(c) < 32 for c in name) or not (member.isfile() or member.isdir())):
                raise ValueError("Unsafe or duplicate CPU original archive entry")
            names.add(name)
            if member.isdir():
                continue
            if name in wanted and member.size > wanted[name]:
                raise ValueError("Oversized CPU receipt/spec/journal")
            h, size, pieces = hashlib.sha256(), 0, []
            stream = archive.extractfile(member)
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                h.update(chunk); size += len(chunk)
                if name in wanted:
                    pieces.append(chunk)
            if size != member.size:
                raise ValueError("Truncated CPU original archive entry")
            hashes[name] = {"sha256": h.hexdigest(), "bytes": size}
            if name in wanted:
                captured[name] = b"".join(pieces)
    return hashes, captured


def review_archive(path, spec, spec_bytes, campaign):
    hashes, captured = archive_inventory(path)
    prefix = "evidence/runs/"
    receipt = json.loads(captured[prefix + "receipt.json"])
    if (receipt["state"] != "COMPLETE_FIXED_WORK_CAMPAIGN" or receipt["gpu_executed"] is not False or
        receipt["execution_scope"] != "CPU_ORCHESTRATION_QUALIFICATION_ONLY" or
        receipt["backend"] != "native-reference" or receipt["planned_jobs"] != 140 or
        receipt["completed_jobs"] != 140 or receipt["finite_work_completed_jobs"] != 140 or
        receipt["actual_selected_cases"] != 140 * SELECTED or
        receipt["spec_sha256"] != hashlib.sha256(spec_bytes).hexdigest() or
        receipt["harness_sha256"] != campaign.harness_sha256() or
        receipt["shared_harness_sha256"] != campaign.SHARED_HARNESS_SHA256 or
        receipt["protocol_sha256"] != campaign.PROTOCOL_SHA256 or
        receipt["reserved_schedule_sha256"] != campaign.RESERVED_SCHEDULE_SHA256 or
        receipt["source_commit"] != campaign.SOURCE_COMMIT or
        receipt["image_digest"] != campaign.IMAGE_DIGEST or
        [job["configuration"] for job in receipt["jobs"]] != spec["schedule"]):
        raise ValueError("CPU campaign receipt completion, scope or source bindings differ")
    if captured[prefix + "spec.json"] != spec_bytes:
        raise ValueError("CPU original specification changed")
    if hashes[prefix + "journal.jsonl"]["sha256"] != receipt["journal_sha256"]:
        raise ValueError("CPU original journal changed")
    journal = [json.loads(line) for line in captured[prefix + "journal.jsonl"].splitlines()]
    starts, finishes = [row for row in journal if row["event"] == "job_start"], [row for row in journal if row["event"] == "job_finish"]
    if ([row["job_index"] for row in starts] != list(range(140)) or
        [row["configuration"] for row in starts] != spec["schedule"] or
        [row["job_index"] for row in finishes] != list(range(140)) or
        len([row for row in journal if row["event"] == "backend_ready"]) != 1 or
        len([row for row in journal if row["event"] == "backend_closed"]) != 1):
        raise ValueError("CPU journal ordering or single-executor lifecycle changed")
    expected_files = {prefix + "spec.json", prefix + "receipt.json", prefix + "journal.jsonl",
                      "evidence/harness.stdout", "evidence/harness.stderr"}
    for index, job in enumerate(receipt["jobs"]):
        if (job["job_index"] != index or job["state"] != "COMPLETE_CASE_LIMIT_LOCAL_ONLY" or
            job["fixed_work_completion"] is not True or job.get("command_guard_expired") is not False or
            job["diagnostics"]["completed_cases"] != SELECTED or job["stop_reason"] is not None or
            job["started_monotonic_ns"] > job["finished_monotonic_ns"] or
            job["job_wall_seconds"] != (job["finished_monotonic_ns"] - job["started_monotonic_ns"]) / 1e9):
            raise ValueError("CPU job quota, interval or stopping guard differs")
        if index and receipt["jobs"][index - 1]["finished_monotonic_ns"] > job["started_monotonic_ns"]:
            raise ValueError("CPU jobs overlapped within one worker")
        if hashes[prefix + job["raw_file"]]["sha256"] != job["raw_sha256"]:
            raise ValueError("CPU original raw trace changed")
        for artifact in job["artifacts"]:
            name = prefix + artifact["file"]
            if hashes[name] != {"sha256": artifact["sha256"], "bytes": artifact["bytes"]}:
                raise ValueError("CPU original artifact bytes or hash changed")
            expected_files.add(name)
        fields = dict(finishes[index]); fields.pop("event"); fields.pop("timestamp_utc"); fields.pop("monotonic_ns")
        if fields != job:
            raise ValueError("CPU original journal job differs from receipt")
    if set(hashes) != expected_files:
        raise ValueError("Unlisted or missing CPU original artifact")
    return receipt, hashes


def pods(namespace, index):
    return json.loads(command(["kubectl", "get", "pods", "-n", namespace, "-l",
                              "job-name=campaign-" + str(index), "-o", "json"]).stdout)


def ready_receipt(namespace, pod):
    result = command(["kubectl", "exec", "-n", namespace, pod, "--", "python3", "-c",
        "from pathlib import Path;p=Path('/evidence/export-ready.json');print(p.read_text() if p.is_file() else '')"], timeout=30)
    return json.loads(result.stdout) if result.stdout.strip() else None


def collect_worker(output, namespace, index):
    data = pods(namespace, index)
    if not data["items"]:
        return {"index": index, "exported": False, "reason": "NO_POD_CREATED"}
    pod = data["items"][0]
    ready = ready_receipt(namespace, pod["metadata"]["name"]) if pod["status"]["phase"] == "Running" else None
    if ready:
        original = output / ("worker-" + str(index) + ".tar.gz")
        with original.open("xb") as stream, (output / ("binary-export-" + str(index) + ".stderr")).open("xb") as errors:
            try:
                subprocess.run(["kubectl", "exec", "-n", namespace, pod["metadata"]["name"], "--", "cat",
                                "/evidence/worker-evidence.tar.gz"], stdout=stream, stderr=errors, check=True, timeout=180)
            except BaseException:
                original.rename(output / ("worker-" + str(index) + "-incomplete-" + uuid4().hex[:8] + ".tar.gz"))
                raise
        if original.stat().st_size != ready["archive_bytes"] or digest(original) != ready["archive_sha256"]:
            original.rename(output / ("worker-" + str(index) + "-corrupt-" + uuid4().hex[:8] + ".tar.gz"))
            raise ValueError("Direct CPU original archive differs from live-pod receipt; namespace retained")
        write(output / ("export-ready-" + str(index) + ".json"), ready)
        command(["kubectl", "exec", "-n", namespace, pod["metadata"]["name"], "--", "python3", "-c",
                 "from pathlib import Path;Path('/evidence/export-confirmed').touch(exist_ok=False)"], timeout=30)
        until = time.monotonic() + 60
        while time.monotonic() < until:
            data = pods(namespace, index)
            pod = data["items"][0]
            if pod["status"]["phase"] in ("Succeeded", "Failed"):
                break
            time.sleep(1)
    path = output / ("pods-" + str(index) + ".json")
    if not path.exists():
        write(path, data)
    logs = subprocess.run(["kubectl", "logs", "-n", namespace, pod["metadata"]["name"]],
                          capture_output=True, timeout=120)
    (output / ("pod-" + str(index) + ".stdout")).write_bytes(logs.stdout)
    (output / ("pod-" + str(index) + ".stderr")).write_bytes(logs.stderr)
    result = {"index": index, "phase": pod["status"]["phase"], "pod": pod["metadata"]["name"],
              "stdout_sha256": digest(output / ("pod-" + str(index) + ".stdout")),
              "stderr_sha256": digest(output / ("pod-" + str(index) + ".stderr")), "exported": False}
    if ready:
        result.update(exported=True, archive_sha256=ready["archive_sha256"], archive_bytes=ready["archive_bytes"],
                      original_returncode=ready["original_returncode"], transport="DIRECT_LIVE_POD_BINARY_TAR_HASH_VERIFIED")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    started_ns, started_utc = time.monotonic_ns(), datetime.now(timezone.utc).isoformat()
    os.environ["KUBECONFIG"] = str(ROOT / ".local/kind.kubeconfig")
    loader = importlib.util.spec_from_file_location("fixed_campaign", ROOT / "scripts/run-fixed-work-campaign.py")
    campaign = importlib.util.module_from_spec(loader); loader.loader.exec_module(campaign)
    if campaign.OVERALL_COMMAND_TIMEOUT_SECONDS != 3600:
        raise ValueError("Final campaign source must bind the approved 3600-second command guard")
    image = campaign.IMAGE_DIGEST
    inspection = json.loads(command(["docker", "image", "inspect", image]).stdout)[0]
    gate = json.loads((ROOT / ".local/ir/kind-verified.json").read_text())
    if (not gate["verified"] or gate["image_id"] != inspection["Id"] or
        inspection["Config"]["Labels"]["org.opencontainers.image.revision"] != campaign.SOURCE_COMMIT):
        raise ValueError("Existing image lacks matching source and prior Kind qualification")
    write(args.output / "image-inspect.json", inspection)
    for node in NODES:
        imported = command(["docker", "exec", node, "ctr", "-n", "k8s.io", "images", "ls", "-q"]).stdout.decode().splitlines()
        if image not in imported:
            candidates = sorted(ref for ref in imported if ref.endswith("@" + image.split("@")[1]))
            if not candidates:
                raise ValueError("Qualified immutable image is absent from existing Kind worker: " + node)
            command(["docker", "exec", node, "ctr", "-n", "k8s.io", "images", "tag", candidates[0], image])
    os.environ["CC_IMAGE_DIGEST"] = image
    spec = campaign.make_spec("native-reference", selected_case_target=SELECTED,
                              safety_timeout_seconds=120, source_commit=campaign.SOURCE_COMMIT)
    spec_bytes = (json.dumps(spec, indent=2) + "\n").encode()
    spec_hash = hashlib.sha256(spec_bytes).hexdigest()
    (args.output / "spec.json").write_bytes(spec_bytes)
    namespace = "cc-fixed-local-" + uuid4().hex[:8]
    common = {"namespace": namespace}
    docs = [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace}},
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": "runner", **common},
         "automountServiceAccountToken": False},
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "campaign-inputs", **common},
         "data": {"run-fixed-work-campaign.py": (ROOT / "scripts/run-fixed-work-campaign.py").read_text(),
                  "run-work-sample.py": (ROOT / "scripts/run-work-sample.py").read_text(),
                  "spec.json": spec_bytes.decode()}}]
    exports, receipts, failure = {}, [], None
    try:
        command(["kubectl", "apply", "-f", "-"], input=json.dumps({"apiVersion": "v1", "kind": "List", "items": docs}).encode())
        denied = subprocess.run(["kubectl", "auth", "can-i", "get", "secrets", "-n", namespace,
            "--as=system:serviceaccount:" + namespace + ":runner"], capture_output=True, timeout=90)
        (args.output / "secret-access.stdout").write_bytes(denied.stdout)
        (args.output / "secret-access.stderr").write_bytes(denied.stderr)
        if denied.stdout.strip() != b"no":
            raise ValueError("CPU runner must not be able to read secrets")
        jobs = [pod_document(namespace, index, image, spec_hash) for index in range(2)]
        for job in jobs:
            command(["kubectl", "apply", "--dry-run=server", "-f", "-"], input=json.dumps(job).encode())
        for job in jobs:
            command(["kubectl", "apply", "-f", "-"], input=json.dumps(job).encode())
        deadline, pending = time.monotonic() + DEADLINE + 90, {0, 1}
        while pending and time.monotonic() < deadline:
            for index in list(pending):
                data = pods(namespace, index)
                if data["items"]:
                    status = data["items"][0]["status"]
                    waiting = [s.get("state", {}).get("waiting", {}).get("reason") for s in status.get("containerStatuses", [])]
                    if status["phase"] in ("Succeeded", "Failed") or any(reason in (
                        "ErrImageNeverPull", "CreateContainerError", "CreateContainerConfigError", "ImagePullBackOff") for reason in waiting):
                        exports[index] = collect_worker(args.output, namespace, index)
                        pending.remove(index)
                    elif status["phase"] == "Running" and ready_receipt(namespace, data["items"][0]["metadata"]["name"]):
                        exports[index] = collect_worker(args.output, namespace, index)
                        pending.remove(index)
            if pending:
                time.sleep(1)
        if pending:
            raise TimeoutError("CPU Kind qualification exceeded the 1200-second pod deadline")
        for index, node in enumerate(NODES):
            exported = exports[index]
            if not exported["exported"] or exported["phase"] != "Succeeded":
                raise RuntimeError("CPU Kind campaign failed; original partial stdout/archive preserved")
            receipt, hashes = review_archive(args.output / ("worker-" + str(index) + ".tar.gz"), spec, spec_bytes, campaign)
            write(args.output / ("artifact-inventory-" + str(index) + ".json"), hashes)
            receipts.append({"node": node, **exported, "completed_jobs": 140, "finite_work_completed_jobs": 140,
                "selected_cases_per_job": SELECTED, "selected_cases": 140 * SELECTED, "gpu_executed": False,
                "actual_total_seconds": receipt["actual_total_seconds"],
                "first_job_started_monotonic_ns": receipt["jobs"][0]["started_monotonic_ns"],
                "last_job_finished_monotonic_ns": receipt["jobs"][-1]["finished_monotonic_ns"],
                "artifact_inventory_sha256": digest(args.output / ("artifact-inventory-" + str(index) + ".json"))})
        result = {"scope": "CPU_KIND_FIXED_WORK_CAMPAIGN_FUNCTIONAL_PIPELINE_ONLY", "verified": True,
            "gpu_executed": False, "image_digest": image, "image_id": inspection["Id"],
            "science_source_commit": campaign.SOURCE_COMMIT, "harness_sha256": campaign.harness_sha256(),
            "shared_harness_sha256": campaign.SHARED_HARNESS_SHA256, "spec_sha256": spec_hash,
            "protocol_sha256": campaign.PROTOCOL_SHA256, "reserved_schedule_sha256": campaign.RESERVED_SCHEDULE_SHA256,
            "qualifier_sha256": digest(Path(__file__)), "started_utc": started_utc,
            "actual_qualification_seconds_before_cleanup": (time.monotonic_ns() - started_ns) / 1e9,
            "jobs_per_worker": 140, "selected_cases_per_job": SELECTED, "total_selected_cases": 1120,
            "safety_timeout_seconds": 120, "workers": receipts, "secret_access": "DENIED",
            "cpu_workers_parallel": True, "gpu_parallel_execution_tested": False, "new_images_built": 0}
        write(args.output / "verified.json", result)
        print(json.dumps(result, indent=2))
    except BaseException as error:
        failure = type(error).__name__
        raise
    finally:
        # Export every available worker before removing emptyDir originals.
        # A running wrapper is asked to stop and package its durable partials.
        export_failures = []
        for index in range(2):
            if index in exports:
                continue
            try:
                data = pods(namespace, index)
                if data["items"] and data["items"][0]["status"]["phase"] == "Running":
                    pod = data["items"][0]["metadata"]["name"]
                    subprocess.run(["kubectl", "exec", "-n", namespace, pod, "--", "python3", "-c",
                        "import os,signal;os.kill(1,signal.SIGTERM)"], capture_output=True, timeout=30)
                    until = time.monotonic() + 60
                    while time.monotonic() < until:
                        data = pods(namespace, index)
                        if (data["items"][0]["status"]["phase"] in ("Succeeded", "Failed") or
                            ready_receipt(namespace, pod)):
                            break
                        time.sleep(1)
                exports[index] = collect_worker(args.output, namespace, index)
            except Exception as error:
                export_failures.append({"index": index, "error_type": type(error).__name__})
        events = subprocess.run(["kubectl", "get", "events", "-n", namespace, "-o", "json"], capture_output=True, timeout=90)
        (args.output / "events.json").write_bytes(events.stdout)
        (args.output / "events.stderr").write_bytes(events.stderr)
        write(args.output / "export-status.json", {"workers": list(exports.values()), "failure_type": failure,
                                                   "export_failures": export_failures})
        preserved = not export_failures and all(exports.get(index, {}).get("exported") or
                     exports.get(index, {}).get("reason") == "NO_POD_CREATED" for index in range(2))
        if preserved:
            command(["kubectl", "delete", "namespace", namespace, "--ignore-not-found=true", "--wait=true", "--timeout=90s"], timeout=100)
        write(args.output / "cleanup.json", {"namespace_deleted": namespace if preserved else False,
                    "namespace_retained_for_evidence_recovery": None if preserved else namespace,
                    "finished_utc": datetime.now(timezone.utc).isoformat(),
                    "total_seconds": (time.monotonic_ns() - started_ns) / 1e9, "failure_type": failure})


if __name__ == "__main__":
    main()
