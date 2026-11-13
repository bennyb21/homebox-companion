#!/usr/bin/env bash
# Called only after the reusable validation workflow and protected garage-test approval.
set -euo pipefail
[[ "$RUN_ID" =~ ^[0-9]+$ ]]
test "$RUN_ID" = "$GITHUB_RUN_ID"
test "$REPOSITORY" = "$GITHUB_REPOSITORY"
# Identity and archive were uploaded by validation before any registry mutation.
gh run download "$RUN_ID" --repo "$REPOSITORY" --name release-image
ARCHIVE_SHA=$(sha256sum release-image.tar | cut -d ' ' -f1)
jq -e --arg sha "$GITHUB_SHA" --arg run "$RUN_ID" --arg repo "$REPOSITORY" --arg archive "$ARCHIVE_SHA" \
  '.sha == $sha and .run_id == $run and .repository == $repo and .archive_sha256 == $archive and (.image_id | test("^sha256:[0-9a-f]{64}$"))' tested-identity.json
docker load -i release-image.tar
IMAGE="ghcr.io/${REPOSITORY,,}"
VERSION=$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
ID=$(docker image inspect homebox-companion:storage-test --format '{{.Id}}')
test "$(docker image inspect "$ID" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$GITHUB_SHA"
test "$(docker image inspect "$ID" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')" = "$VERSION"
test "$(jq -er .image_id tested-identity.json)" = "$ID"
test "$(jq -er .version tested-identity.json)" = "$VERSION"
PRIVATE_CONFIG=$(mktemp -d)
export DOCKER_CONFIG="$PRIVATE_CONFIG"
cleanup() {
  docker logout ghcr.io >/dev/null 2>&1 || true
  rm -rf -- "$PRIVATE_CONFIG"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Enumerate only this run's checkpoints, failing closed on API/download/expiry errors.
gh api "repos/$REPOSITORY/actions/runs/$RUN_ID/artifacts?per_page=100" --paginate --slurp > publication-artifacts.json
jq -e 'type == "array"' publication-artifacts.json >/dev/null
jq -r '.[] | .artifacts[] | select(.name | startswith("publication-state-")) | [.name, .expired] | @tsv' publication-artifacts.json > publication-artifacts.tsv
KNOWN_DIGEST=''
while IFS=$'\t' read -r name expired; do
  [[ "$name" =~ ^publication-state-[0-9]+$ ]]
  test "$expired" = false
  gh run download "$RUN_ID" --repo "$REPOSITORY" --name "$name" --dir "$PRIVATE_CONFIG/$name"
  checkpoint="$PRIVATE_CONFIG/$name/publication-state.json"
  jq -e --slurpfile accepted tested-identity.json 'del(.digest) == $accepted[0]' "$checkpoint"
  previous=$(jq -er .digest "$checkpoint")
  [[ "$previous" == "$IMAGE@sha256:"* && "${previous##*@sha256:}" =~ ^[0-9a-f]{64}$ ]]
  test -z "$KNOWN_DIGEST" || test "$KNOWN_DIGEST" = "$previous"
  KNOWN_DIGEST="$previous"
done < publication-artifacts.tsv
printf '%s' "$GH_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin
# Existing versions may only resume the exact durable accepted artifact.
TOKEN=$(curl --fail --silent --show-error -u "$GITHUB_ACTOR:$GH_TOKEN" "https://ghcr.io/token?scope=repository:${REPOSITORY,,}:pull" | jq -er .token)
STATUS=$(curl --silent --show-error -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" -H 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' "https://ghcr.io/v2/${REPOSITORY,,}/manifests/$VERSION")
case "$STATUS" in
  404)
    test -z "$KNOWN_DIGEST"
    docker tag "$ID" "$IMAGE:$VERSION"
    docker push "$IMAGE:$VERSION"
    ;;
  200)
    docker pull "$IMAGE:$VERSION"
    test "$(docker image inspect "$IMAGE:$VERSION" --format '{{.Id}}')" = "$ID"
    test "$(docker image inspect "$IMAGE:$VERSION" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$GITHUB_SHA"
    test "$(docker image inspect "$IMAGE:$VERSION" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')" = "$VERSION"
    ;;
  *) echo "Refusing registry status $STATUS" >&2; exit 1 ;;
esac
DIGEST=$(docker image inspect "$IMAGE:$VERSION" --format '{{json .RepoDigests}}' | jq -er --arg prefix "$IMAGE@" '[.[] | select(startswith($prefix))] | if length == 1 then .[0] else error("ambiguous digest") end')
[[ "$DIGEST" == "$IMAGE@sha256:"* && "${DIGEST##*@sha256:}" =~ ^[0-9a-f]{64}$ ]]
test -z "$KNOWN_DIGEST" || test "$KNOWN_DIGEST" = "$DIGEST"
# Uploaded by an always() step; the pre-push identity survives even runner loss.
jq --arg digest "$DIGEST" '. + {digest:$digest}' tested-identity.json > publication-state.json.tmp
mv publication-state.json.tmp publication-state.json
# Visibility is an explicit administrator prerequisite, not a best-effort mutation.
docker logout ghcr.io
docker pull "$DIGEST"
test "$(docker image inspect "$DIGEST" --format '{{.Id}}')" = "$ID"
printf '%s' "$GH_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin
docker tag "$DIGEST" "$IMAGE:garage-test"
docker push "$IMAGE:garage-test"
docker logout ghcr.io
docker pull "$IMAGE:garage-test"
test "$(docker image inspect "$IMAGE:garage-test" --format '{{json .RepoDigests}}' | jq -er --arg prefix "$IMAGE@" '.[] | select(startswith($prefix))')" = "$DIGEST"
cp publication-state.json release-manifest.json
