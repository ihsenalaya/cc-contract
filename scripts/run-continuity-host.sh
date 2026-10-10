#!/usr/bin/env bash
# Invoked only inside a separately approved retained-VM window.
# No provisioning, driver changes, reset, MIG or guest shutdown command.
set -euo pipefail
image="${1:?immutable image required}"
output="${2:?new evidence directory required}"
registry_config="${3:-/run/cc-continuity-registry}"
[[ "$image" =~ ^ghcr.io/ihsenalaya/cc-contract-continuity@sha256:[a-f0-9]{64}$ ]]
[[ "$output" =~ ^/home/cccontract/cc-continuity-[a-zA-Z0-9-]+$ ]]
[[ "$registry_config" == /run/cc-continuity-registry ]]
trap 'sudo -n rm -rf /run/cc-continuity-registry' EXIT
umask 077
mkdir "$output"
uname -r > "$output/kernel.txt"
nvidia-smi --query-gpu=driver_version,name --format=csv,noheader > "$output/driver.txt"
nvidia-smi conf-compute -f > "$output/cc-mode.txt"
nvidia-smi conf-compute -e > "$output/cc-environment.txt"
mokutil --sb-state > "$output/secure-boot.txt"
grep -Fx '6.8.0-1066-azure-fde' "$output/kernel.txt" >/dev/null
grep -E '^595\.91\.07,.*H100' "$output/driver.txt" >/dev/null
grep -E 'CC status: ON|CC Status[[:space:]]*:[[:space:]]*ON' "$output/cc-mode.txt" >/dev/null
grep -F 'PRODUCTION' "$output/cc-environment.txt" >/dev/null
grep -F 'SecureBoot enabled' "$output/secure-boot.txt" >/dev/null
timeout 180 sudo -n docker --config "$registry_config" pull "$image" > "$output/pull.log" 2>&1
sudo docker image inspect "$image" > "$output/image-inspect.json"
# The image's non-root UID owns only this new result directory.
mkdir "$output/data"
sudo chown 10001:10001 "$output/data"
date --utc --iso-8601=ns > "$output/run-start.txt"
exit_code=0
timeout --signal=TERM --kill-after=15s 540 sudo docker run --rm \
  --name cc-continuity-pilot-v01 --runtime=nvidia --gpus all --ulimit memlock=-1:-1 --network none \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=16m --memory 2g --cpus 2 \
  --mount "type=bind,src=$output/data,dst=/evidence" \
  "$image" --backend cuda --output /evidence/runs \
  > "$output/runner.stdout" 2> "$output/runner.stderr" || exit_code=$?
date --utc --iso-8601=ns > "$output/run-end.txt"
printf '%s\n' "$exit_code" > "$output/exit-code.txt"
# Stop a timed-out container before exporting partial evidence.
if [[ "$exit_code" -ne 0 ]]; then
  sudo docker stop --time 3 cc-continuity-pilot-v01 >/dev/null 2>&1 || true
fi
sudo chown -R "$(id -u):$(id -g)" "$output/data"
python3 - "$output" <<'PY'
import hashlib,json,pathlib,sys
p=pathlib.Path(sys.argv[1])
files={str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(p.rglob('*')) if f.is_file()}
(p/'hashes.json').write_text(json.dumps(files,indent=2)+'\n')
PY
exit "$exit_code"
