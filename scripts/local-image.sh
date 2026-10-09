#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
export PYTHONPATH="$task_root/src"
mkdir -p .local/images
task_commit="$(git rev-parse HEAD)"
task_image="cc-contract-cpu:$task_commit"
case "${1:-}" in
  build)
    bash scripts/quick-check.sh
    if [ -n "$(git status --porcelain -- src Dockerfile .dockerignore)" ]; then
      echo 'Commit image sources before building to preserve provenance' >&2; exit 1
    fi
    task_commit="$(git rev-parse HEAD)"
    task_image="cc-contract-cpu:$task_commit"
    task_context="$(mktemp -d)"
    trap 'rm -rf "$task_context"' EXIT
    git archive "$task_commit" | tar -xf - -C "$task_context"
    docker build --platform linux/amd64 --file "$task_context/Dockerfile" --build-arg "CC_COMMIT=$task_commit" --tag "$task_image" "$task_context"
    rm -rf "$task_context"
    trap - EXIT
    docker image inspect "$task_image" > .local/images/inspect.json
    task_image_id="$(docker image inspect --format '{{.Id}}' "$task_image")"
    docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --env "CC_BUILD_IMAGE_ID=$task_image_id" --env CC_IMAGE_DIGEST=LOCAL_IMAGE_UNPUBLISHED "$task_image" > .local/images/selftest.jsonl
    python3 scripts/verify_jsonl.py .local/images/selftest.jsonl
    docker run --rm --network none --read-only --entrypoint python3 "$task_image" -m pip list --format json > .local/images/python-packages.json
    printf '%s\n' "$task_image" > .local/images/name
    printf '%s\n' "$task_image_id" > .local/images/id
    ;;
  publish)
    task_image="$(cat .local/images/name)"
    task_image_id="$(cat .local/images/id)"
    test "$task_image_id" = "$(docker image inspect --format '{{.Id}}' "$task_image")"
    python3 scripts/check-image-gate.py
    task_remote="ghcr.io/ihsenalaya/cc-contract-cpu:$task_commit"
    docker tag "$task_image" "$task_remote"
    docker push "$task_remote" | tee .local/images/push.log
    docker image inspect "$task_remote" > .local/images/published-inspect.json
    docker buildx imagetools inspect "$task_remote" --format '{{json .Manifest}}' > .local/images/registry-manifest.json
    task_digest="$(python3 -c 'import json; print(json.load(open(".local/images/registry-manifest.json"))["digest"])')"
    printf '%s@%s\n' "${task_remote%:*}" "$task_digest" | tee .local/images/remote-digest
    ;;
  *) echo 'usage: local-image.sh build|publish' >&2; exit 2 ;;
esac
