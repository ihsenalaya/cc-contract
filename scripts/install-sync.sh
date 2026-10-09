#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Preserve unrelated entries. A five-minute retry handles reconnection after failure.
task_entries="$(crontab -l 2>/dev/null | sed '/# cc-contract-sync$/d' || true)"
{
  [ -z "$task_entries" ] || echo "$task_entries"
  printf '0 */2 * * * /bin/bash "%s/scripts/sync.sh" # cc-contract-sync\n' "$task_root"
  printf '@reboot /bin/bash "%s/scripts/sync.sh" # cc-contract-sync\n' "$task_root"
  printf '*/5 * * * * /bin/bash "%s/scripts/retry-sync.sh" # cc-contract-sync\n' "$task_root"
} | crontab -
crontab -l | sed -n '/# cc-contract-sync$/p'
