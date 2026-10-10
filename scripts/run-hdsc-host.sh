#!/usr/bin/env bash
# Called only by hdsc-window.py after fresh plan-bound authorization.
set -euo pipefail
work="${1:?private prepared directory required}"
[[ "$work" =~ ^/home/cccontract/cc-hdsc-[a-z0-9-]+$ ]]
output="$work/evidence"
mkdir "$output"
cleanup() {
  sudo -n docker stop --time 3 cc-hdsc-core cc-hdsc-ai >/dev/null 2>&1 || true
  sudo -n rm -rf /run/cc-hdsc-registry
  sudo -n chown -R "$(id -u):$(id -g)" "$output"
}
trap cleanup EXIT
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
# Bound new storage; never prune existing images, model assets or evidence.
[[ $(df --output=avail -B1 "$work" | tail -1) -ge 12884901888 ]]
chmod -R a+rX "$work/model"
chmod a+r "$work/plan.json" "$work/approval.json" "$work/run-hdsc-section.py"
mkdir "$output/data"
sudo -n chown 10001:10001 "$output/data"
for section in core ai; do
  image=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["images"][sys.argv[2]])' "$work/plan.json" "$section")
  [[ "$image" =~ ^ghcr.io/ihsenalaya/cc-contract-hdsc(-ai)?@sha256:[a-f0-9]{64}$ ]]
  timeout 240 sudo -n docker --config /run/cc-hdsc-registry pull "$image" > "$output/pull-$section.log" 2>&1
  sudo -n docker image inspect "$image" > "$output/image-$section.json"
  remaining=$(python3 -c 'import datetime,json,sys; print(int((datetime.datetime.fromisoformat(json.load(open(sys.argv[1]))["expires_utc"])-datetime.datetime.now(datetime.timezone.utc)).total_seconds())-120)' "$work/approval.json")
  [[ "$remaining" -gt 0 ]]
  date --utc --iso-8601=ns > "$output/$section-start.txt"
  timeout --signal=TERM --kill-after=10s "$remaining" sudo -n docker run --rm \
    --name "cc-hdsc-$section" --runtime=nvidia --gpus all --ulimit memlock=-1:-1 \
    --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
    --tmpfs /tmp:rw,nosuid,nodev,size=256m --shm-size=256m --memory 8g --cpus 4 \
    --mount "type=bind,src=$output/data,dst=/evidence" \
    --mount "type=bind,src=$work/model,dst=/model,readonly" \
    --mount "type=bind,src=$work/plan.json,dst=/plan.json,readonly" \
    --mount "type=bind,src=$work/approval.json,dst=/approval.json,readonly" \
    --mount "type=bind,src=$work/run-hdsc-section.py,dst=/runner.py,readonly" \
    --entrypoint python "$image" /runner.py --section "$section" --model /model \
    --plan /plan.json --approval /approval.json --output "/evidence/$section" \
    > "$output/$section.stdout" 2> "$output/$section.stderr"
  date --utc --iso-8601=ns > "$output/$section-end.txt"
done
