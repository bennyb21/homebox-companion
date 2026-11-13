# Fork release and update runbook

## Identity and supported delivery target

This fork uses plain SemVer: Python package `0.1.0`, Docker version tag `0.1.0`,
and a future Git release tag `v0.1.0`. The upstream base is separately recorded as
Duelion/homebox-companion v3.2.2 (`e6fbb4dc9de30c5de7187e25d7be30cfead47034`).
This is not an upstream 3.x release. Preserve GPL notices and publish the exact
corresponding source before distributing an image. `/app/LICENSE` and OCI source,
revision, version and license labels travel with the runtime image.

In-app update checks default OFF; opt-in checks target bennyb21/homebox-companion,
not Duelion. Docker updates are independent. Research defaults OFF, performs no
startup search, and has not been tested against a paid/live provider. See
[research limitations](product-research.md) and [native capture](native-capture.md).

The tested release target is **linux/amd64**. Do not advertise arm64 runtime
acceptance from an amd64 test. UID/GID remain 1000:1000, port 8000, one application
worker, persistent `/app/data` (settings, field preferences and SQLite jobs).
Never copy personal settings, API keys or inventory photos into a build context.

## Gates before any public publication

Local tests do not establish GitHub Actions success, GHCR availability, package
visibility, or a successful anonymous public pull. None is implied by this code.
Before enabling publication, an administrator must:

1. Publish/review the corresponding source and configure branch protection.
2. Create **garage-test** and **garage-stable** GitHub environments, with required
   reviewers, restricted trusted branches/tags, no self-approval and no bypass.
   Merely naming an environment in YAML does NOT activate protection rules.
3. Confirm Actions/package permission and quota; configure the GHCR package as
   public (or arrange a separately reviewed private-registry policy). First push
   can create a private package: the anonymous pull gate will deliberately fail.
   A failed visibility gate does not authorize overwriting its version tag; inspect
   and recover deliberately, or use a new version.
4. Update package version, project lock entry and Docker version default together.
   Do not upgrade dependencies as part of a version-only change.

`docker-publish.yml` is manual only. It invokes the reusable validation workflow
at the **same dispatch SHA**. Python quality/unit checks, frontend checks/browser
suite, pinned Homebox compatibility matrix and production-image tests must all
succeed. The terminal gate rejects failed, cancelled, skipped or missing jobs.
PR workflows have no package-write job or publish secrets.

The image job builds once, tests that actual image (storage plus legacy/manual/
automatic capture and research/restart), then saves it as an Actions artifact.
The publisher downloads that artifact from its own run, verifies OCI revision
and version, and publishes it without rebuilding. Immutable-by-policy version
tags are never overwritten; unexpected HTTP statuses fail closed. It performs
an anonymous digest pull/readback before moving `garage-test` and records the
SHA, version, image identity, digest and run ID in `release-manifest.json`.
Archive this manifest beyond the 90-day artifact retention period.

After a separate pilot and backup/rollback review, manually dispatch `promote.yml`
with the successful candidate run ID. The protected stable approval must inspect
pilot evidence. Promotion verifies the successful run, source SHA, image labels,
manifest identity and current test-channel digest; it tags/pushes the **same digest**
to `garage-stable` and verifies anonymous readback. No rebuild and no automatic
production deploy. A Git release `vVERSION` must point to the manifest SHA and
quote that digest; release creation alone never publishes an image.

## Local image acceptance (no public writes)

Use a clean committed checkout. On Linux, explicitly select the local Docker daemon:

```sh
unset DOCKER_CONTEXT DOCKER_HOST
D='docker --host unix:///var/run/docker.sock'
SHA=$(git rev-parse HEAD)
$D build --build-arg REVISION="$SHA" -t homebox-companion:local-acceptance .
npm --prefix frontend ci
npm --prefix frontend run build
# Host Playwright Chromium must be installed; see tests/README.md.
TEST_COMPANION_IMAGE=homebox-companion:local-acceptance \
TEST_HOMEBOX_VERSION=0.27.1 DOCKER_HOST=unix:///var/run/docker.sock \
  .venv/bin/pytest -m live tests/test_companion_container_live.py \
  tests/test_fullstack_smoke.py tests/test_research_fullstack.py
```

The fullstack harness mounts a **test-only provider entrypoint** read-only into the
image and persists `/app/data`; it never mounts application source or installs
pytest into the image. Its browser uses the frontend built inside the image.
Synthetic provider calls preserve actual image handling, schema validation,
Homebox APIs and independent photo/field readback. Storage tests and the Compose
drill also run the unmodified production command. This is not model-quality proof.

For a two-build drill, build an actual prior source checkout as A, not just a
second label on B. Explicitly label unreleased test builds as such. Then:

```sh
TEST_IMAGE_A=homebox-companion:baseline \
TEST_IMAGE_B=homebox-companion:local-acceptance \
TEST_HOMEBOX_VERSION=0.27.1 HBC_DELIVERY_EVIDENCE=/absolute/private/evidence \
DOCKER_HOST=unix:///var/run/docker.sock \
  .venv/bin/pytest -m live tests/test_delivery_compose_live.py
```

The drill uses a temporary **127.0.0.1-bound localhost registry**, real push/pull
and Compose up, bind-mounted Companion storage and a named Homebox data volume.
It does not modify daemon insecure-registry settings. Homebox has a stable local
URL across restarts because research authorization scopes include server identity.
It checks changed container/image identity, settings bytes, applied job state,
native item JSON and downloaded photo hash after A → B → A and after stopped-writer
backup/restore. It empties/repopulates only its own Homebox volume for the restore
proof, then removes its own containers/volume. Private scratch backups/settings
may contain synthetic credentials; do not publish them. Retain compact evidence
and image handles; remove owned bulky scratch directories after review.

## Later production update — requires separate authorization

Read the actual host Compose and overrides first. Do not use a GitHub repository
URL as `image:`. After the public-pull gate, the intended reference is
`ghcr.io/bennyb21/homebox-companion:garage-stable`; this document does not claim it
already exists. A fixed `@sha256:...` deliberately prevents channel updates.
Keep Homebox independently pinned and unchanged.

1. Record the running Companion digest, source version, Compose and private config.
2. Stop Companion and back up all its `/app/data`, including settings and SQLite
   WAL/SHM files. For online SQLite backup use its backup API, never copy only a
   live `.sqlite3` file. Back up Homebox database AND attachments consistently
   using its supported stopped-writer procedure; keep keys/permissions private.
3. `docker compose pull companion` then `docker compose up -d companion`.
   Verify actual image digest, health, login, routes and a synthetic photo/field
   save with independent Homebox readback. Reauthorize queued jobs as needed;
   unknown paid outcomes must not be blindly replayed.
4. Roll back by setting `image: ghcr.io/bennyb21/homebox-companion@sha256:OLD`,
   pulling and recreating. If schemas/settings migrated, stop writers and restore
   the compatible backup first. Never `down -v`, delete production appdata or run
   two writers against the same SQLite data. Preserve the original official image
   digest in the private deployment record too.

No Unraid deployment, live inventory pilot or real paid research is authorized by
these commands. Local acceptance is necessary, not production acceptance.
