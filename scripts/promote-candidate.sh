#!/usr/bin/env bash
set -euo pipefail
[[ "$CANDIDATE_RUN" =~ ^[0-9]+$ ]]
gh api "repos/$REPOSITORY/actions/runs/$CANDIDATE_RUN" > candidate-run.json
jq -e --arg repo "$REPOSITORY" '.conclusion == "success" and .status == "completed" and .event == "workflow_dispatch" and .path == ".github/workflows/docker-publish.yml" and .head_repository.full_name == $repo' candidate-run.json
gh run download "$CANDIDATE_RUN" --repo "$REPOSITORY" --name release-manifest
SHA=$(jq -er .head_sha candidate-run.json)
DIGEST=$(jq -er .digest release-manifest.json)
VERSION=$(jq -er .version release-manifest.json)
ID=$(jq -er .image_id release-manifest.json)
IMAGE="ghcr.io/${REPOSITORY,,}"
test "$(jq -er .sha release-manifest.json)" = "$SHA"
test "$(jq -er .run_id release-manifest.json)" = "$CANDIDATE_RUN"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$DIGEST" =~ ^${IMAGE}@sha256:[0-9a-f]{64}$ ]]
export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d)
docker pull "$DIGEST"
test "$(docker image inspect "$DIGEST" --format '{{.Id}}')" = "$ID"
test "$(docker image inspect "$DIGEST" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$SHA"
test "$(docker image inspect "$DIGEST" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')" = "$VERSION"
# Refuse a stale candidate if a later pilot has replaced the test channel.
docker pull "$IMAGE:garage-test"
test "$(docker image inspect "$IMAGE:garage-test" --format '{{json .RepoDigests}}' | jq -er --arg prefix "$IMAGE@" '.[] | select(startswith($prefix))')" = "$DIGEST"
printf '%s' "$GH_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin
docker tag "$DIGEST" "$IMAGE:garage-stable"
docker push "$IMAGE:garage-stable"
docker logout ghcr.io
docker pull "$IMAGE:garage-stable"
test "$(docker image inspect "$IMAGE:garage-stable" --format '{{json .RepoDigests}}' | jq -er --arg prefix "$IMAGE@" '.[] | select(startswith($prefix))')" = "$DIGEST"
printf 'Promoted %s (version %s, source %s)\n' "$DIGEST" "$VERSION" "$SHA"
