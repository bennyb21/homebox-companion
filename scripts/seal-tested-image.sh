#!/usr/bin/env bash
# Run only after actual-image acceptance; upload both outputs before publishing.
set -euo pipefail
VERSION=$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
ID=$(docker image inspect "$TEST_COMPANION_IMAGE" --format '{{.Id}}')
[[ "$ID" =~ ^sha256:[0-9a-f]{64}$ ]]
test "$(docker image inspect "$ID" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$GITHUB_SHA"
test "$(docker image inspect "$ID" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')" = "$VERSION"
docker save "$TEST_COMPANION_IMAGE" -o release-image.tar
ARCHIVE_SHA=$(sha256sum release-image.tar | cut -d ' ' -f1)
jq -n --arg sha "$GITHUB_SHA" --arg version "$VERSION" --arg id "$ID" --arg archive "$ARCHIVE_SHA" --arg run "$GITHUB_RUN_ID" --arg repo "$GITHUB_REPOSITORY" \
  '{sha:$sha,version:$version,image_id:$id,archive_sha256:$archive,run_id:$run,repository:$repo}' > tested-identity.json
