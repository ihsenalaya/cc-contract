#!/usr/bin/env bash
set -euo pipefail
umask 077
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$task_root/.local/sync"
exec >>"$task_root/.local/sync/events.log" 2>&1
exec 9>"$task_root/.local/sync/lock"
flock -n 9 || exit 0
unset GH_DEBUG
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
cd "$task_root"
echo "$(date -u +%FT%TZ) sync starting"
trap 'echo "$(date -u +%FT%TZ) sync failed exit=$?"' ERR
if [ -f .local/sync/last-attempt ]; then
  task_last="$(cat .local/sync/last-attempt)"
  if [ "$(( $(date +%s) - task_last ))" -gt 10800 ]; then
    echo "$(date -u +%FT%TZ) interruption detected: >3h since last attempt; retrying"
  fi
fi
date +%s > .local/sync/last-attempt
timeout 180 bash scripts/quick-check.sh
command -v trivy >/dev/null
timeout 180 trivy fs --scanners secret --exit-code 1 --no-progress --skip-dirs .git --skip-dirs .local --skip-dirs results/raw --skip-dirs .terraform .
# Stage only the public allowlist after checks; never raw data or cloud state.
git add -- README.md LICENSE CITATION.cff AGENTS.md .gitignore .dockerignore pyproject.toml Dockerfile Dockerfile.cuda Dockerfile.ir src tests scripts docs infrastructure kubernetes experiments results/manifests .github
python3 scripts/release-guard.py
if ! git diff --cached --quiet; then
  git commit -m "Checkpoint verified project artifacts $(date -u +%FT%TZ)"
fi
timeout 120 git push origin main
echo "$(date -u +%FT%TZ) sync completed commit=$(git rev-parse HEAD)"
date +%s > .local/sync/last-success
