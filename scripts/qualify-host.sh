#!/usr/bin/env bash
# Runs ONLY on the approved new temporary H100; never changes kernel or driver.
set -euo pipefail
umask 077
task_image="${1:?immutable image reference required}"
[[ "$task_image" =~ ^ghcr.io/ihsenalaya/cc-contract-cuda@sha256:[a-f0-9]{64}$ ]]
task_directory="${CC_EVIDENCE_DIRECTORY:-$HOME/cc-contract-evidence}"
mkdir -p "$task_directory"
cd "$task_directory"
task_failed=0
task_allowed=1
capture() {
  task_label="$1"; shift
  set +e
  timeout 180 "$@" > "$task_label.stdout" 2> "$task_label.stderr"
  task_code=$?
  set -e
  printf '%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$task_label" "$task_code" >> commands.tsv
  if [ "$task_code" -ne 0 ]; then
    task_failed=1
    case "$task_label" in
      cc-mode|cc-environment|secure-boot|cpu-attestation|gpu-attestation) task_allowed=0 ;;
    esac
  fi
}
capture kernel uname -a
capture nvidia-info nvidia-smi -q
capture cc-mode nvidia-smi conf-compute -f
capture cc-environment nvidia-smi conf-compute -e
capture secure-boot mokutil --sb-state
capture cpu-attestation sudo -n cpu-attestation
capture gpu-attestation sudo -n gpu-attestation
capture python-torch python3 -c 'import json,torch; print(json.dumps({"torch":torch.__version__,"cuda":torch.version.cuda,"available":torch.cuda.is_available()}))'
# Capture verifier identities; raw reports remain private.
for task_tool in cpu-attestation gpu-attestation nvidia-smi; do
  task_path="$(command -v "$task_tool" || true)"
  [ -z "$task_path" ] || sha256sum "$task_path" >> tool-hashes.txt
done
grep -Eq 'CC status:[[:space:]]*ON' cc-mode.stdout || task_allowed=0
grep -q 'PRODUCTION' cc-environment.stdout || task_allowed=0
grep -q 'SecureBoot enabled' secure-boot.stdout || task_allowed=0
grep -q 'Attested Guest Successfully' cpu-attestation.stdout || task_allowed=0
grep -q 'GPU Attestation is Successful' gpu-attestation.stdout || task_allowed=0
if [ "$task_allowed" -eq 1 ]; then
  task_commit="$(sudo -n docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$task_image")"
  [[ "$task_commit" =~ ^[a-f0-9]{40}$ ]]
  task_run_id="gpu-$(date -u +%Y%m%dT%H%M%SZ)-$(cat /proc/sys/kernel/random/uuid)"
  capture cuda-reference sudo -n docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --runtime=nvidia --gpus all --ulimit memlock=-1:-1 --env "CC_RUN_ID=$task_run_id" --env "CC_COMMIT=$task_commit" --env "CC_IMAGE_DIGEST=$task_image" "$task_image"
else
  printf '%s\tcuda-reference\tNOT_RUN_ATTESTATION_OR_CC_GATE\n' "$(date -u +%FT%TZ)" >> commands.tsv
  task_failed=1
fi
sha256sum ./*.stdout ./*.stderr commands.tsv > SHA256SUMS
exit "$task_failed"
