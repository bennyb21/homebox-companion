# Optional grounded product research

Research is **off by default**. Capture, review, and save do not require it. No source/confidence fields are added to Homebox. Research never changes an item without selecting fields and confirming adoption.

## Configuration (existing settings permissions)

Open **Settings → Product research**, then enable **Enable product research**.
The sole eligible existing profile is selected automatically; with several,
choose one explicitly. The server persists only its name and the enabled flag,
reusing the stored key by reference. No key copy/re-entry or provider test occurs.
The settings page reads back the saved configuration before reporting success.

Eligibility is checked on the server against the adapter's existing credential,
model-name and official-endpoint constraints and the installed LiteLLM catalog's
OpenAI web-search flag. The UI uses these server results rather than its own
model list. Catalog eligibility is **not** verification of API key validity,
model access, billing or live research quality. Unsupported profiles show a reason;
edit the existing AI profile's model while leaving its key unchanged, then reload
research settings. Custom API bases and provider-prefixed model names are not
accepted by this adapter; an explicitly configured `https://api.openai.com/v1`
is accepted unchanged, as well as an unset base. Dispatch still uses only the fixed
official Responses endpoint. Profile primary/fallback status does not select research.
Research settings use the same authenticated Homebox-identity policy as existing
LLM-profile settings; this does not introduce a separate admin role.

The existing file configuration remains supported:

```yaml
research_enabled: false
research_profile_name: existing-openai-profile
```

Enable only after agreeing API billing, model access, and a pilot budget. No key,
billing, model access or live search quality is verified by offline tests.
ChatGPT/Codex subscriptions do not establish API credit.

There is one provider: LiteLLM SDK `aresponses` directly to `https://api.openai.com/v1/responses`, hosted `web_search`, required tool use, at most one tool call, 2400 output tokens and a 45-second total deadline. Store/background/stream are disabled, SDK retries are zero, no Router/fallback/paid repair is used. A final transport checks the serialized request contract and refuses a second POST, a different URL, or redirects. No source URLs, previews, favicons, or remote images are fetched. These are local request limits, **not a guaranteed monetary spending cap**.

## Review workflow

Open **Research product data** in capture review or on an unsaved summary item. The summary entry opens that item's editor at the research panel; it does not start a search. Written/uncertain rows cannot be reopened as fresh research drafts. Disabled research links to Settings. The number and optional manufacturer are prefilled where known. Confirm whether the exact identifier is a part number or model number; serial numbers are not accepted as an identifier kind. Manufacturer can remain unknown. Keep punctuation/suffixes unchanged. This version preserves bounded embedded spaces literally (for example `A 000 123 45 67`); it rejects leading/trailing whitespace, URL/control-character input rather than silently repairing it.

Only public identity is sent to the provider: no item IDs, collection/account IDs, location, notes, purchase price, serial field, images or inventory description. Input cannot guarantee that a person never pastes private information into a product field; review it before confirming.

Provider annotations and completed search actions are required. Claimed JSON URLs alone are insufficient. Similar suffixes and manufacturer collisions yield ambiguity, not adopted facts. Citations identify **model synthesis**, not independently fetched/verified source quotations. There are no vehicle fitment, VIN or safety guarantees. Model output cannot target purchase price or arbitrary fields.

Select proposals individually. Current values (including intentionally empty values) remain unchanged until adoption. Only unambiguous native TEXT fields with server-controlled meanings are eligible: Manufacturer/Hersteller, Part number/Part number (OEM)/Teilenummer, Model number/Modellnummer, Specifications/Technical specifications/Technische Daten, and coarse Vehicle family/Fahrzeugzuordnung. The latter is a sourced family/model assignment only, not VIN-, engine-, model-year-specific compatibility or installation approval. MSRP never maps to purchase price. Unrelated/native sibling field IDs are preserved. Changed drafts/templates reject adoption. Draft reviews expire after 15 minutes and do not survive a server restart; capture/save still works.

## Saved-item background jobs

The review panel links to `/research`, where saved items can be selected and jobs queued. Refresh shows their durable status; the browser may close while a running server finishes the job. The worker never writes research automatically. After a matched result, select fields and choose **Apply selected to Homebox**. The server rereads item and template, rejects stale bases, writes under a Companion lock, and immediately reads back selected values.

SQLite is `data/research.sqlite3` (in the standard image: `/app/data/research.sqlite3`). Persist the normal `/app/data` volume. SQLite WAL, busy timeout, transactional schema initialization, atomic job claims, payload-bound idempotency keys and single-flight aliases prevent local duplicate dispatch. Current limits: 100 retained jobs globally, 10 queued/active jobs per user+collection scope, two running globally and one per scope, 10 aliases per single-flight job, seven-day retention. Expired terminal jobs are purged at enqueue. A process lock deliberately requires **one application worker**; multiple uvicorn workers are not supported for research.

Credentials remain in memory, not SQLite. Every job read/apply requires fresh Homebox identity, collection membership and item access; dispatch rechecks them and the item/template/configuration fingerprints. After restart, undispatched jobs conservatively become `needs_auth` and need the same user's **Reauthorize queued job** action (including configured-key mode). Dispatched but unconfirmed jobs become `unknown_outcome`; interrupted writes become `apply_unknown`. Neither automatically retries. Successful persisted results remain available after restart.

Cancelling queued work prevents dispatch; cancellation during a call discards the result but cannot refund costs or guarantee provider-side cancellation. Unknown outcomes require inspection and a deliberate **Start a new paid attempt** decision. There is no automatic retry/backoff because this version never assumes a failed paid POST was unbilled. A stale saved-item review currently requires manual comparison rather than an automatic rebase.

Homebox does not provide an atomic item compare-and-swap here. An external writer can race between fresh read and write; the local lock/readback is **not** an exactly-once or absolute lost-update guarantee.

## Backup and rollback

Stop Companion before copying the database, or use SQLite's backup API while running; do not copy a live WAL database as a lone `.sqlite3` file. Retain settings separately under their normal secret-management policy. Schema version 1 rejects future versions. Restore only a compatible backup into the same deployment's data volume, then start one worker. Recovery never replays a possibly dispatched paid POST. Offline tests exercise SQLite backup/restore and actual Python/Companion process restarts; they do not certify a production container-volume backup procedure.

## Offline verification

```sh
.venv/bin/pytest tests/test_research.py tests/test_research_evidence.py \
  tests/test_research_api.py tests/test_research_jobs.py tests/test_research_job_security.py -q
npm --prefix frontend run verify
# Build frontend first, then run the isolated Homebox acceptance:
env -u DOCKER_CONTEXT DOCKER_HOST=unix:///var/run/docker.sock \
  TEST_HOMEBOX_VERSION=0.27.1 .venv/bin/pytest tests/test_research_fullstack.py -m live -q
```

The fullstack harness uses synthetic Responses via MockTransport through the real SDK, the real browser and Companion API, isolated Homebox, independent readback and an actual Companion restart. It does not make paid provider calls. Legacy capture/chat regression remains in `tests/test_fullstack_smoke.py`.
