"""Review preserved E0 evidence locally; never provisions or accesses a GPU.

MAA signing keys are obtained over verified HTTPS from the fixed trusted issuer.
Local GPU HMAC receipts are explicitly NOT independently authenticated here.
"""
import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import tarfile
import urllib.request

ISSUER = "https://sharedeus2.eus2.attest.azure.net"
if not __debug__:
    raise RuntimeError("Evidence review requires Python assertions enabled")


def decode(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def tokens(text):
    return list(dict.fromkeys(re.findall(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", text)))


def verify_cpu(token, jwks, expected_vm_id, observation_time):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    header, payload, signature = token.split(".")
    h, claims = json.loads(decode(header)), json.loads(decode(payload))
    assert h["alg"] == "RS256" and claims["iss"] == ISSUER
    keys = [k for k in jwks["keys"] if k.get("kid") == h["kid"] and k.get("kty") == "RSA"]
    assert len(keys) == 1
    k = keys[0]
    public = rsa.RSAPublicNumbers(int.from_bytes(decode(k["e"]), "big"), int.from_bytes(decode(k["n"]), "big")).public_key()
    public.verify(decode(signature), (header + "." + payload).encode(), padding.PKCS1v15(), hashes.SHA256())
    assert claims["nbf"] <= observation_time + 5 < claims["exp"]
    assert observation_time - 60 <= claims["iat"] <= observation_time + 5
    assert claims["x-ms-azurevm-vmid"].lower() == expected_vm_id.lower()
    assert claims["secureboot"] is True
    assert claims["x-ms-azurevm-kerneldebug-enabled"] is False
    assert claims["x-ms-azurevm-hypervisordebug-enabled"] is False
    tee = claims["x-ms-isolation-tee"]
    assert tee["x-ms-attestation-type"] == "sevsnpvm"
    assert tee["x-ms-compliance-status"] == "azure-compliant-cvm"
    assert tee["x-ms-sevsnpvm-is-debuggable"] is False
    return {"scope": "MAA_SIGNATURE_AND_SELECTED_CLAIMS", "signature_verified": True,
            "vm_identity_matches": True, "secureboot": True,
            "tee_type": "sevsnpvm", "azure_compliance": True,
            "provider_TEE_signing_key_binding_independently_checked": False}


def review_cuda(rows):
    cases = [r for r in rows if r["record_type"] == "case"]
    environments = [r for r in rows if r["record_type"] == "environment"]
    assert len(rows) == 55 and len(cases) == 54 and len(environments) == 1
    assert environments[0]["device_count"] == 1
    planned = set()
    for repeat in range(3):
        for family in ["T01", "T02", "T03", "T05"]:
            for round_index in range(3 if family in ["T02", "T05"] else 1):
                planned.add((family, repeat, 128, repeat * 10 + round_index, False))
        for size in [1, 2, 31, 32, 33, 255, 256, 257, 4096]:
            planned.add(("T06", repeat, size, repeat, False))
        planned.add(("E0_KERNEL_REFERENCE", repeat, 4096, repeat, True))
    seen = set()
    for r in cases:
        identity = (r["family"], r["repeat"], r["size"], r["generation"], r["kernel"])
        assert identity in planned and identity not in seen
        seen.add(identity)
        expected = [r["generation"] if i == 0 else (i * 17 + r["generation"] * 31) % 8191 - 4095 for i in range(r["size"])]
        if r["kernel"]:
            expected = [expected[0]] + [2 * x + 1 for x in expected[1:]]
        assert all(type(x) is int for x in r["observed"] + r["expected"])
        assert r["expected"] == expected and r["observed"] == expected
        assert r["gpu_executed"] is True and r["seed"] == 0
        assert r["scope"] == "REAL_CUDA_CC_NOT_YET_QUALIFIED"
        assert r["verdict"] == r["oracle_verdict"] == "PASS"
        assert math.isfinite(r["duration_seconds"]) and r["duration_seconds"] >= 0
        assert r["synchronization"] == ("event_wait_then_stream_sync" if r["family"] == "T03" else "same_stream_then_stream_sync")
    assert seen == planned
    assert len({r["run_id"] for r in cases}) == 1
    assert len({(r["git_commit"], r["image_digest"]) for r in cases}) == 1
    assert re.fullmatch(r"[a-f0-9]{40}", cases[0]["git_commit"])
    assert re.fullmatch(r"ghcr.io/ihsenalaya/cc-contract-cuda@sha256:[a-f0-9]{64}", cases[0]["image_digest"])
    return {"scope": "BOUNDED_REAL_CUDA_INTEGER_QUALIFICATION", "observations": 54,
            "independent_array_comparison": "PASS", "families": dict(Counter(r["family"] for r in cases)),
            "repeats": 3, "independent_campaigns": 1, "git_commit": cases[0]["git_commit"],
            "image_digest": cases[0]["image_digest"], "scientific_superiority_claim": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--vm-identity", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory
    receipt = json.loads((directory / "collection.json").read_text())
    archive_path = directory / receipt["archive_file"]
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == receipt["archive_sha256"]
    identity = json.loads(args.vm_identity.read_text())
    vm_id = identity[0]["instances"][0]["attributes"]["virtual_machine_id"]
    jwks_path = directory / "cpu-signing-jwks.json"
    if not jwks_path.exists():
        with urllib.request.urlopen(ISSUER + "/certs", timeout=30) as response:
            assert response.url.startswith(ISSUER + "/")
            data = response.read(1024 * 1024 + 1)
        assert len(data) <= 1024 * 1024
        json.loads(data)
        with jwks_path.open("xb") as f:
            f.write(data)
    jwks = json.loads(jwks_path.read_text())
    with tarfile.open(archive_path) as archive:
        names = archive.getnames()
        assert len(names) == len(set(names))
        assert all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in names)
        def read(name):
            member = archive.getmember("cc-contract-evidence/" + name)
            assert member.isfile()
            return archive.extractfile(member).read()
        for line in read("SHA256SUMS").decode().splitlines():
            digest, name = line.split(maxsplit=1)
            assert hashlib.sha256(read(name.removeprefix("./"))).hexdigest() == digest
        commands = {}
        for line in read("commands.tsv").decode().splitlines():
            stamp, label, code = line.split("\t")
            assert label not in commands
            commands[label] = {"timestamp_utc": stamp, "exit_code": int(code)}
        for label in ["kernel", "nvidia-info", "cc-mode", "cc-environment", "secure-boot", "cpu-attestation", "gpu-attestation", "cuda-reference"]:
            assert commands[label]["exit_code"] == 0
        cpu_tokens = tokens(read("cpu-attestation.stdout").decode())
        assert len(cpu_tokens) == 1
        when = datetime.fromisoformat(commands["cpu-attestation"]["timestamp_utc"].replace("Z", "+00:00")).timestamp()
        cpu = verify_cpu(cpu_tokens[0], jwks, vm_id, when)
        gpu_tokens = tokens(read("gpu-attestation.stdout").decode())
        assert len(gpu_tokens) == 2
        gpu = [json.loads(decode(t.split(".")[1])) for t in gpu_tokens]
        assert all(json.loads(decode(t.split(".")[0]))["alg"] == "HS256" for t in gpu_tokens)
        assert all(r["iss"] == "LOCAL_GPU_VERIFIER" for r in gpu)
        outer = next(r for r in gpu if "x-nvidia-overall-att-result" in r)
        inner = next(r for r in gpu if "measres" in r)
        assert outer["x-nvidia-overall-att-result"] is True and inner["measres"] == "success"
        assert outer["eat_nonce"] == inner["eat_nonce"]
        assert inner["dbgstat"] == "disabled" and inner["secboot"] is True
        checks = {k: v for k, v in inner.items() if k.startswith("x-nvidia-gpu-") and type(v) is bool}
        assert len(checks) == 16 and all(v is True for v in checks.values())
        rows = [json.loads(line) for line in read("cuda-reference.stdout").decode().splitlines()]
        result = {"schema_version": 1, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                  "scope": "PARTIAL_E0_REAL_GPU_QUALIFICATION", "archive_sha256": receipt["archive_sha256"],
                  "cpu_jwks_sha256": hashlib.sha256(jwks_path.read_bytes()).hexdigest(),
                  "cpu_attestation": cpu, "gpu_attestation": {"scope": "LOCAL_HARDWARE_VERIFIER_RECEIPTS",
                  "reported_checks_all_true": True, "checks": checks, "hmac_receipts_independently_authenticated": False,
                  "exported_hardware_quote_independently_reverified": False, "NRAS_token": "NOT_RUN"},
                  "cuda": review_cuda(rows),
                  "host_pytorch_exit_code": commands.get("python-torch", {}).get("exit_code"),
                  "container_pytorch_exit_code": commands.get("pytorch-components", {}).get("exit_code"),
                  "paired_inference_exit_code": commands.get("torch-inference", {}).get("exit_code"),
                  "container_component_and_inference_results_require_separate_review": True}
    output = directory / ("review-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + ".json")
    with output.open("x") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
