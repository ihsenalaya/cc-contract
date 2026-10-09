#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
task_last=0
[ ! -f "$task_root/.local/sync/last-success" ] || task_last="$(cat "$task_root/.local/sync/last-success")"
if [ "$(( $(date +%s) - task_last ))" -ge 7200 ]; then
  exec bash "$task_root/scripts/sync.sh"
fi
