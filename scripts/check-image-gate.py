import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
image_id = (root / ".local/images/id").read_text().strip()
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
inspection = json.loads((root / ".local/images/inspect.json").read_text())[0]
assert inspection["Id"] == image_id
assert inspection["Config"]["User"] == "10001:10001"
assert inspection["Config"]["Labels"]["org.opencontainers.image.revision"] == commit
assert not subprocess.check_output(["git", "status", "--porcelain", "--", "src", "Dockerfile", ".dockerignore"], cwd=root, text=True).strip()
gate = json.loads((root / ".local/integration/latest.json").read_text())
assert gate["verified"] and gate["build_image_id"] == image_id
assert gate["git_commit"] == commit
assert len(set(gate["workers"])) == 2
print("local build, image identity, nonroot user and two-worker qualification verified")
