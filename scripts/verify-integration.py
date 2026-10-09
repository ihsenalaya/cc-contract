import hashlib
import json
from pathlib import Path
import sys
from verify_jsonl import verify


def main():
    root = Path(__file__).resolve().parents[1]
    directory = Path(sys.argv[1])
    pods = json.loads((directory / "pods.json").read_text())["items"]
    assert len(pods) == 2
    workers = [p["spec"]["nodeName"] for p in pods]
    assert len(set(workers)) == 2
    image_id = (root / ".local/images/id").read_text().strip()
    inspect = json.loads((root / ".local/images/inspect.json").read_text())[0]
    commit = inspect["Config"]["Labels"]["org.opencontainers.image.revision"]
    summaries = []
    for p in pods:
        assert p["status"]["phase"] == "Succeeded"
        assert p["spec"]["automountServiceAccountToken"] is False
        assert not p["spec"].get("volumes")
        status = p["status"]["containerStatuses"][0]
        assert status["state"]["terminated"]["exitCode"] == 0
        # Local containerd image IDs may be config or manifest IDs; retain actual ID.
        manifest = verify(directory / (p["metadata"]["name"] + ".jsonl"))
        assert manifest["git_commit"] == commit
        assert manifest["build_image_id"] == image_id
        summaries.append({"pod": p["metadata"]["name"], "node": p["spec"]["nodeName"], "runtime_image_id": status["imageID"], "run_id": manifest["run_id"], "raw_sha256": manifest["raw_sha256"]})
    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
    result = {"verified": True, "scope": "CPU_SIMULATION_ONLY", "build_image_id": image_id, "git_commit": commit, "workers": workers, "runs": summaries, "evidence_sha256": evidence, "evidence_directory": str(directory.relative_to(root))}
    (directory / "verified.json").write_text(json.dumps(result, indent=2) + "\n")
    (root / ".local/integration/latest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
