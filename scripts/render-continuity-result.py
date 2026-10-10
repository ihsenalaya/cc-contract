"""Render public derived tables from independently audited original pilot records."""
import argparse
import csv
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    r = args.window
    original = r / "offline"
    records_path = original / "data/runs/runs.jsonl"
    rows = [json.loads(line) for line in records_path.read_text().splitlines()]
    spec = importlib.util.spec_from_file_location("independent_audit", ROOT / "scripts/audit-continuity-pilot.py")
    auditor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auditor)
    schedule = json.loads((ROOT / "experiments/state-continuity-schedule-v0.1.json").read_text())
    audit = auditor.audit(rows, schedule)
    if not audit["real_cuda"]:
        raise ValueError("Real CUDA records required")
    recorded_audit = json.loads((r / "independent-gpu-audit.json").read_text())
    if recorded_audit["runs_sha256"] != sha(records_path) or recorded_audit["counts"] != audit["counts"]:
        raise ValueError("Original independent audit does not match")
    release = json.loads((r / "release.json").read_text())
    independent_off = json.loads((r / "independent-off-verification.json").read_text())
    if release["power_state"] != "PowerState/deallocated" or independent_off["power_state"] != "PowerState/deallocated":
        raise ValueError("Deallocation proof required before reporting")
    plan = json.loads((r / "plan.json").read_text())
    image = json.loads((original / "image-inspect.json").read_text())[0]
    if plan["image"] not in image["RepoDigests"]:
        raise ValueError("Executed OCI digest differs from approved image")
    commit = image["Config"]["Labels"]["org.opencontainers.image.revision"]
    host = {key: (original / name).read_text().strip() for key, name in
            (("driver", "driver.txt"), ("kernel", "kernel.txt"), ("cc_mode", "cc-mode.txt"),
             ("cc_environment", "cc-environment.txt"), ("secure_boot", "secure-boot.txt"))}
    if (host["driver"] != "595.91.07, NVIDIA H100 NVL" or host["kernel"] != "6.8.0-1066-azure-fde" or
            host["cc_mode"] != "CC status: ON" or host["cc_environment"] != "CC Environment: PRODUCTION" or
            host["secure_boot"] != "SecureBoot enabled"):
        raise ValueError("Qualified host evidence differs")
    started = json.loads((r / "start-request.json").read_text())["utc"]
    vm_seconds = (datetime.fromisoformat(release["utc"]) - datetime.fromisoformat(started)).total_seconds()
    summary = json.loads((original / "data/runs/summary.json").read_text())
    if summary["runs_sha256"] != sha(records_path) or summary["actual_runs"] != 50:
        raise ValueError("Summary identity differs")
    metrics = []
    for group in ("HEALTHY", "L1", "L2", "C1", "C2"):
        group_rows = [x for x in rows if x["group"] == group]
        activated = sum(x["activated"] for x in group_rows)
        detected = sum(x["activated"] and x["verdict"]["classification"] == "STATE_CONTINUITY_VIOLATION" for x in group_rows)
        metrics.append(dict(fault=group, runs=len(group_rows), activated=activated,
                            cuda_success=sum(x["observation"]["execution_status"] == "CUDA_SUCCESS" for x in group_rows),
                            detected=detected, missed=activated - detected,
                            false_positives=sum(x["verdict"]["classification"] != "PASS" for x in group_rows) if group == "HEALTHY" else None,
                            mean_worker_seconds=statistics.mean(x["execution_ns"] / 1e9 for x in group_rows),
                            mean_detector_microseconds=statistics.mean(x["detection_ns"] / 1e3 for x in group_rows)))
    # Do not turn a negative result into an exception or alter the frozen GO rule.
    go = (all(x["cuda_success"] == 10 and x["missed"] == 0 for x in metrics) and
          metrics[0]["false_positives"] == 0 and sum(x["detected"] > 0 for x in metrics[1:]) >= 2)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "faults.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(metrics[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(metrics)
    derived = []
    for row in rows:
        observed = row["verdict"]["observed_state"]
        derived.append(dict(run_id=row["run_id"], block=row["block"], seed=row["seed"], scenario=row["group"],
                            variant=row["fault"], activated=row["activated"], execution_status=row["observation"]["execution_status"],
                            classification=row["verdict"]["classification"], expected_buffer_id=1, expected_generation=2,
                            expected_payload_tag=row["expected_state"]["payload_tag"], **observed,
                            worker_seconds=row["execution_ns"] / 1e9, detector_microseconds=row["detection_ns"] / 1e3,
                            image=plan["image"], scientific_source_commit=commit, **host))
    with (args.output / "runs.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(derived[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(derived)
    result = dict(protocol=plan["protocol"], state="COMPLETED_AND_INDEPENDENTLY_AUDITED_GPU_PILOT",
                  decision="GO_MECHANISM_FEASIBILITY_ONLY" if go else "NO_GO",
                  actual_runs=50, metrics=metrics, scientific_source_commit=commit,
                  controller_source_commit=plan["source_commit"], image=plan["image"], host=host,
                  actual_harness_wall_seconds=summary["wall_seconds"],
                  VM_start_request_utc=started, VM_deallocated_utc=release["utc"],
                  VM_request_to_deallocation_seconds=vm_seconds,
                  observed_billing_cost=None, approved_forecast_budget_usd=5,
                  original_archive_sha256=sha(r / "originals.tar.gz"), original_archive_bytes=(r / "originals.tar.gz").stat().st_size,
                  raw_runs_sha256=sha(records_path), independent_audit_sha256=sha(r / "independent-gpu-audit.json"),
                  independent_off_proof_sha256=sha(r / "independent-off-verification.json"),
                  plan_sha256=sha(r / "plan.json"), approval_sha256=sha(r / "approval.json"),
                  table_sha256={name: sha(args.output / name) for name in ("faults.csv", "runs.csv")},
                  resources_destroyed=0, VM_and_disk_retained=True, further_H100_use_authorized=False,
                  discovered_vulnerabilities=0, B3_B4_superiority_established=False,
                  total_GPU_instrumentation_overhead_measured=False,
                  independent_GPU_attestation_validated_by_this_pilot=False,
                  historical_E4_E5_results_changed=False)
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"decision": result["decision"], "runs": 50, "VM_seconds": vm_seconds, "metrics": metrics}))


if __name__ == "__main__":
    main()
