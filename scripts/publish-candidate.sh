#!/usr/bin/env bash
# Called only after the reusable validation workflow and protected garage-test approval.
set -euo pipefail
gh run download "$RUN_ID" --repo "$REPOSITORY" --name release-image
docker load -i release-image.tar
IMAGE="ghcr.io/${REPOSITORY,,}"
VERSION=$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
ID=$(docker image inspect homebox-companion:storage-test --format '{{.Id}}')
test "$(docker image inspect "$ID" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$GITHUB_SHA"
test "$(docker image inspect "$ID" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')" = "$VERSION"
printf '%s' "$GH_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin
# Existing immutable version or any auth/transport error is a hard stop.
TOKEN=$(curl --fail --silent --show-error -u "$GITHUB_ACTOR:$GH_TOKEN" "https://ghcr.io/token?scope=repository:${REPOSITORY,,}:pull" | jq -er .token)
STATUS=$(curl --silent --show-error -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "https://ghcr.io/v2/${REPOSITORY,,}/manifests/$VERSION")
test "$STATUS" = 404
docker tag "$ID" "$IMAGE:$VERSION"
docker push "$IMAGE:$VERSION"
DIGEST=$(docker image inspect "$IMAGE:$VERSION" --format '{{json .RepoDigests}}' | jq -er --arg prefix "$IMAGE@" '.[] | select(startswith($prefix))')
[[ "$DIGEST" =~ @sha256:[0-9a-f]{64}$ ]]
# Visibility is an explicit administrator prerequisite, not a best-effort mutation.
docker logout ghcr.io
export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d)
docker pull "$DIGEST"
test "$(docker image inspect "$DIGEST" --format '{{.Id}}')" = "$ID"
printf '%s' "$GH_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin
docker tag "$DIGEST" "$IMAGE:garage-test"
docker push "$IMAGE:garage-test"
docker logout ghcr.io
docker pull "$IMAGE:garage-test"
test "$(docker image inspect "$IMAGE:garage-test" --format '{{json .RepoDigests}}' | jq -er --arg prefix "$IMAGE@" '.[] | select(startswith($prefix))')" = "$DIGEST"
jq -n --arg digest "$DIGEST" --arg version "$VERSION" --arg sha "$GITHUB_SHA" --arg id "$ID" --arg run "$RUN_ID" \
  '{digest:$digest,version:$version,sha:$sha,image_id:$id,run_id:$run}' > release-manifest.json
