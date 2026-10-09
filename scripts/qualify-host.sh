#!/usr/bin/env bash
# Runs ONLY on the approved new temporary H100; never changes kernel or driver.
set -euo pipefail
umask 077
task_image="${1:?immutable image reference required}"
[[ "$task_image" =~ ^ghcr.io/ihsenalaya/cc-contract-cuda@sha256:[a-f0-9]{64}$ ]]
task_ir="${2:-}"
task_torch="${3:-}"
task_model="${4:-}"
task_corpus="${5:-}"
task_sample_spec="${6:-}"
task_sample_harness="${7:-}"
task_sample_spec_sha="${8:-}"
task_sample_harness_sha="${9:-}"
task_sample_kind="${10:-sequential}"
task_helper="${11:-}"
task_helper_sha="${12:-}"
[[ "$task_sample_kind" == sequential || "$task_sample_kind" == work || "$task_sample_kind" == campaign ]]
task_sample_entry=run-sequential-sample.py
task_sample_label=sequential-sample
if [ "$task_sample_kind" == work ]; then
  task_sample_entry=run-work-sample.py
  task_sample_label=work-sample
fi
if [ "$task_sample_kind" == campaign ]; then
  task_sample_entry=run-fixed-work-campaign.py
  task_sample_label=fixed-work-campaign
  [ -n "$task_helper" ] && [[ "$task_helper_sha" =~ ^[a-f0-9]{64}$ ]]
fi
[ -z "$task_ir" ] || [[ "$task_ir" =~ ^ghcr.io/ihsenalaya/cc-contract-ir@sha256:[a-f0-9]{64}$ ]]
[ -z "$task_torch" ] || [[ "$task_torch" =~ ^ghcr.io/ihsenalaya/cc-contract-torch@sha256:[a-f0-9]{64}$ ]]
task_directory="${CC_EVIDENCE_DIRECTORY:-$HOME/cc-contract-evidence}"
mkdir -p "$task_directory"
cd "$task_directory"
task_failed=0
task_allowed=1
capture() {
  task_label="$1"; shift
  task_started="$(date -u +%FT%T.%NZ)"
  task_start_seconds="$(date +%s.%N)"
  set +e
  task_timeout=180
  [ "$task_label" != torch-inference ] || task_timeout=900
  [ "$task_label" != sequential-sample ] || task_timeout=1200
  [ "$task_label" != work-sample ] || task_timeout=1800
  [ "$task_label" != fixed-work-campaign ] || task_timeout=3600
  timeout "$task_timeout" "$@" > "$task_label.stdout" 2> "$task_label.stderr"
  task_code=$?
  task_end_seconds="$(date +%s.%N)"
  set -e
  printf '%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$task_label" "$task_code" >> commands.tsv
  printf '%s\t%s\t%s\t%s\t%s\n' "$task_started" "$task_label" "$task_start_seconds" "$task_end_seconds" "$task_code" >> timings.tsv
  if [ "$task_code" -ne 0 ]; then
    task_failed=1
    case "$task_label" in
      kernel-version|driver-version|cc-mode|cc-environment|secure-boot|cpu-attestation|gpu-attestation|cuda-reference|ir-reference|pytorch-components|sequential-sample|work-sample|fixed-work-campaign) task_allowed=0 ;;
    esac
  fi
}
capture kernel uname -a
capture kernel-version uname -r
capture nvidia-info nvidia-smi -q
capture driver-version nvidia-smi --query-gpu=driver_version --format=csv,noheader
capture cc-mode nvidia-smi conf-compute -f
capture cc-environment nvidia-smi conf-compute -e
capture secure-boot mokutil --sb-state
capture cpu-attestation sudo -n cpu-attestation
capture gpu-attestation sudo -n gpu-attestation
if [ -z "$task_torch" ] && [ -z "$task_sample_spec" ]; then
  capture python-torch python3 -c 'import json,torch; print(json.dumps({"torch":torch.__version__,"cuda":torch.version.cuda,"available":torch.cuda.is_available()}))'
fi
# Capture verifier identities; raw reports remain private.
for task_tool in cpu-attestation gpu-attestation nvidia-smi; do
  task_path="$(command -v "$task_tool" || true)"
  [ -z "$task_path" ] || sha256sum "$task_path" >> tool-hashes.txt
done
grep -Eq 'CC status:[[:space:]]*ON' cc-mode.stdout || task_allowed=0
grep -qx '6.8.0-1066-azure-fde' kernel-version.stdout || task_allowed=0
grep -qx '595.91.07' driver-version.stdout || task_allowed=0
grep -q 'PRODUCTION' cc-environment.stdout || task_allowed=0
grep -q 'SecureBoot enabled' secure-boot.stdout || task_allowed=0
grep -q 'Attested Guest Successfully' cpu-attestation.stdout || task_allowed=0
grep -q 'GPU Attestation is Successful' gpu-attestation.stdout || task_allowed=0
if [ "$task_allowed" -eq 1 ]; then
  task_commit="$(sudo -n docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$task_image")"
  [[ "$task_commit" =~ ^[a-f0-9]{40}$ ]]
  task_run_id="gpu-$(date -u +%Y%m%dT%H%M%SZ)-$(cat /proc/sys/kernel/random/uuid)"
  capture cuda-reference sudo -n docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --runtime=nvidia --gpus all --ulimit memlock=-1:-1 --env "CC_RUN_ID=$task_run_id" --env "CC_COMMIT=$task_commit" --env "CC_IMAGE_DIGEST=$task_image" "$task_image"
  if [ "$task_allowed" -eq 1 ] && [ -n "$task_ir" ]; then
    task_ir_options=()
    [ -n "$task_sample_spec" ] || task_ir_options=(--allow-unsupported)
    capture ir-reference sudo -n docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --runtime=nvidia --gpus all --ulimit memlock=-1:-1 --env "CC_RUN_ID=$task_run_id-ir" --env "CC_IMAGE_DIGEST=$task_ir" "$task_ir" qualify --backend cuda "${task_ir_options[@]}" --emit-records
  fi
  if [ "$task_allowed" -eq 1 ] && [ -n "$task_sample_spec" ]; then
    [ -n "$task_ir" ] && [ -z "$task_torch" ] && [ -z "$task_model" ]
    [[ "$task_sample_spec_sha" =~ ^[a-f0-9]{64}$ ]]
    [[ "$task_sample_harness_sha" =~ ^[a-f0-9]{64}$ ]]
    printf '%s  %s\n%s  %s\n' "$task_sample_spec_sha" "$task_sample_spec" "$task_sample_harness_sha" "$task_sample_harness" | sha256sum -c -
    task_helper_mount=()
    if [ "$task_sample_kind" == campaign ]; then
      printf '%s  %s\n' "$task_helper_sha" "$task_helper" | sha256sum -c -
      task_helper_mount=(--mount "type=bind,source=$task_helper,target=/run-work-sample.py,readonly")
    fi
    sudo -n install -d -m 700 -o 10001 -g 10001 "$task_directory/$task_sample_label"
    capture "$task_sample_label" sudo -n docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --runtime=nvidia --gpus all --ulimit memlock=-1:-1 --env "CC_IMAGE_DIGEST=$task_ir" --mount "type=bind,source=$task_sample_spec,target=/sample-spec.json,readonly" --mount "type=bind,source=$task_sample_harness,target=/$task_sample_entry,readonly" "${task_helper_mount[@]}" --mount "type=bind,source=$task_directory/$task_sample_label,target=/evidence" --entrypoint python3 "$task_ir" "/$task_sample_entry" --spec /sample-spec.json --spec-sha256 "$task_sample_spec_sha" --output /evidence/runs --backend cuda
  fi
  if [ "$task_allowed" -eq 1 ] && [ -n "$task_torch" ]; then
    capture pytorch-components sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL --security-opt no-new-privileges --runtime=nvidia --gpus all --ulimit memlock=-1:-1 --env "CC_RUN_ID=$task_run_id-torch" --env "CC_IMAGE_DIGEST=$task_torch" "$task_torch" components --device cuda
    if [ "$task_allowed" -eq 1 ] && [ -n "$task_model" ] && [ -n "$task_corpus" ]; then
      sudo -n install -d -m 700 -o 10001 -g 10001 "$task_directory/inference"
      capture torch-inference sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL --security-opt no-new-privileges --runtime=nvidia --gpus all --ulimit memlock=-1:-1 --env "CC_RUN_ID=$task_run_id-inference" --env "CC_IMAGE_DIGEST=$task_torch" --mount "type=bind,source=$task_model,target=/model,readonly" --mount "type=bind,source=$task_directory/inference,target=/evidence" "$task_torch" inference --device cuda --model /model --corpus "/model/$task_corpus" --output /evidence/run
    fi
  fi
else
  printf '%s\tcuda-reference\tNOT_RUN_ATTESTATION_OR_CC_GATE\n' "$(date -u +%FT%TZ)" >> commands.tsv
  task_failed=1
fi
# Includes partial inference evidence, without ever archiving model weights.
sudo -n chown -R "$(id -u):$(id -g)" "$task_directory"
find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
exit "$task_failed"
