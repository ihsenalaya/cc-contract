#!/usr/bin/env bash
# Called only by hdsc-window.py after fresh plan-bound authorization.
set -euo pipefail
work="${1:?private prepared directory required}"
[[ "$work" =~ ^/home/cccontract/cc-hdsc-[a-z0-9-]+$ ]]
output="$work/evidence"
container_prefix="cc-hdsc-${work##*/}"
mkdir "$output"
cleanup() {
  local status=$?
  trap - EXIT
  set +e
  sudo -n docker stop --time 3 "$container_prefix-core" "$container_prefix-ai" >/dev/null 2>&1 || true
  sudo -n rm -rf /run/cc-hdsc-registry
  sudo -n chown -R "$(id -u):$(id -g)" "$output"
  if [[ "$status" -ne 0 ]]; then
    # Preserve diagnostics over the existing SSH connection before the controller
    # deallocates. Full originals stay on disk; bounded tails contain no registry
    # credential file or model/evaluation payloads. Never retry a failed job.
    printf 'HDSC guest failed with exit status %s\n' "$status" >&2
    for log in core.stderr ai.stderr pull-core.log pull-ai.log; do
      if [[ -f "$output/$log" ]]; then
        printf '\n%s (last 16384 bytes):\n' "$log" >&2
        tail -c 16384 "$output/$log" >&2
      fi
    done
  fi
  exit "$status"
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
  if [[ "$section" == core ]]; then
    sudo -n docker run --rm --network none --read-only --entrypoint compute-sanitizer "$image" --version > "$output/sanitizer-version.txt"
    sudo -n docker run --rm --network none --read-only --entrypoint compute-sanitizer "$image" --help > "$output/sanitizer-help.txt"
  fi
  remaining=$(python3 -c 'import datetime,json,sys; print(int((datetime.datetime.fromisoformat(json.load(open(sys.argv[1]))["expires_utc"])-datetime.datetime.now(datetime.timezone.utc)).total_seconds())-120)' "$work/approval.json")
  [[ "$remaining" -gt 0 ]]
  date --utc --iso-8601=ns > "$output/$section-start.txt"
  timeout --signal=TERM --kill-after=10s "$remaining" sudo -n docker run --rm \
    --name "$container_prefix-$section" --runtime=nvidia --gpus all --ulimit memlock=-1:-1 \
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
python3 - "$output" <<'PY'
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]);hashes={}
for path in sorted(root.rglob('*')):
    if path.is_file():
        digest=hashlib.sha256()
        with path.open('rb') as file:
            for part in iter(lambda:file.read(1024**2),b''):digest.update(part)
        hashes[str(path.relative_to(root))]=digest.hexdigest()
(root/'hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
PY
