"""Separated status/output baselines and fail-closed Compute Sanitizer parsing."""
import re

TOOLS = ("memcheck", "racecheck", "initcheck", "synccheck")


def cuda_status(observation):
    status = observation.get("execution_status")
    return {"CUDA_SUCCESS": "PASS", "CUDA_ERROR": "ALERT"}.get(status, "UNSUPPORTED")


def output_only(expected_output, actual_output):
    # Deliberately no logical identity, version or injection input.
    if type(expected_output) is not int or type(actual_output) is not int:
        return "INVALID_TEST"
    return "PASS" if actual_output == expected_output else "ALERT"


def sanitizer_command(tool, worker, fault, active):
    if tool not in TOOLS:
        raise ValueError("Unknown sanitizer")
    return ["compute-sanitizer", "--tool", tool, "--error-exitcode", "86",
            "--target-processes", "all", "--", str(worker), fault, str(int(active))]


def sanitizer_result(tool, returncode, stdout, stderr, observation):
    if tool not in TOOLS:
        raise ValueError("Unknown sanitizer")
    text = stdout + "\n" + stderr
    if observation.get("execution_status") == "UNSUPPORTED":
        return {"classification": "UNSUPPORTED", "reason": "no_cuda_device"}
    unsupported = ("not supported under confidential", "not supported in confidential",
                   "debugging is not supported", "not supported in cc-on",
                   "confidential compute mode detected. compute-sanitizer will be disabled.")
    if any(message in text.lower() for message in unsupported):
        return {"classification": "UNSUPPORTED", "reason": "tool_rejected_environment"}
    if "compute-sanitizer will be disabled" in text.lower():
        return {"classification": "INFRA_FAILURE", "reason": "instrumentation_disabled_unknown_cause"}
    pattern = r"RACECHECK SUMMARY:\s*(\d+)\s+hazard" if tool == "racecheck" else r"ERROR SUMMARY:\s*(\d+)\s+errors?"
    counts = re.findall(pattern, text)
    if len(counts) != 1 or observation.get("execution_status") != "CUDA_SUCCESS":
        return {"classification": "INFRA_FAILURE", "reason": "no_complete_cuda_and_tool_report"}
    count = int(counts[0])
    if (count == 0 and returncode != 0) or (count > 0 and returncode != 86):
        return {"classification": "INFRA_FAILURE", "reason": "tool_exit_report_disagreement"}
    return {"classification": "ALERT" if count else "PASS", "diagnostics": count}
