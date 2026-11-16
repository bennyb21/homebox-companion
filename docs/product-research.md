# Optional grounded product research

Research is **off by default**. Capture, review, and save do not require it. No source/confidence fields are added to Homebox. Research never changes an item without selecting fields and confirming adoption.

## Configuration (existing settings permissions)

Open **Settings → Product research**, then enable **Enable product research**.
The sole eligible existing profile is selected automatically; with several,
choose one explicitly. The server persists only its name and the enabled flag,
reusing the stored key by reference. No key copy/re-entry or provider test occurs.
The settings page reads back the saved configuration before reporting success.

Eligibility is checked on the server against the adapter's existing credential,
model-name and official-endpoint constraints, exact first-party model metadata,
or the installed LiteLLM catalog's OpenAI web-search flag. The API reports
`eligibility_source` (`official_metadata`, `runtime_catalog`, or `unverified`).
The UI uses these server results rather than its own
model list. Catalog eligibility is **not** verification of API key validity,
model access, billing or live research quality. Unsupported profiles show a reason;
create/edit an AI profile, then reload research settings. A dedicated **Research** role
can use a different model with an explicit reference to an existing OpenAI credential.
Selecting an existing Primary/Fallback here preserves its capture role. See
[model configuration](model-configuration.md) for credential boundaries, migration,
effective Compose/UI precedence and optional model-specific reasoning. Higher
reasoning effort shares the fixed output budget and can leave incomplete output.
 Custom API bases and provider-prefixed model names are not
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

Open **Research product data** in capture review or on an unsaved summary item. This opens the editor without starting a search. **Research this item** explicitly submits the existing product context and associated photos. There is no individual-number search form, exact-number echo gate or required manufacturer. Literal observed markings remain context; the model may propose a correction for manual review.

Product title, description, manufacturer/model/part/serial markings and allowlisted identification/technical custom fields may be sent. Arbitrary purchase/payment/account/location metadata is not forwarded. Photos are actual validated image bytes (up to eight, bounded combined size), not remote URLs. Saved-item photos are read from native attachments under current access rights with bounded IDs, sizes and no redirects. Review text and photos for private information before dispatch.

Suggestions are **not independently verified** and never provide installation, vehicle-fitment or safety approval. Values are editable and selectable. Provider citation links appear prominently as display metadata, separately from data acceptance. A missing citation or different proposed number does not discard otherwise usable suggestions. No model-supplied source URL is fetched; only validated HTTP(S) citation links are displayed.

## Response and review contract

The adapter requests a bounded JSON object with `fields` and optional `ambiguity`. Flat useful fields, structured specifications and legacy candidate responses are also readable. Unknown or invalid individual fields are ignored. Duplicate/malformed JSON, refusals and incomplete responses remain diagnosed. No per-field citation mapping, citation-position proof, exact echo or wording gate is claimed. There is no second model call or paid repair.

The parser returns editable AI suggestions, not certified facts. Legacy `identity` requests remain accepted for compatibility and use the same simplified provider/output contract; `identity_confirmed` is ignored, not an attestation. New draft UI requests carry `context`, and saved-item UI requests send only the selected item ID and idempotency key so the server derives fresh context.

## Diagnostics and explicit profile tests

`ResearchResult` retains schema version 1 and existing statuses. Its optional
`diagnostic` contains required `code` and `stage`, plus fixed safe `message`,
optional `http_status`, sanitized `request_id`, `dispatch_started`, application
`correlation_id`, and `incomplete_reason` (`max_output_tokens`, `content_filter`,
or `other`). Old durable results without diagnostics remain readable. The HTTP
request ID is not a LiteLLM-encoded response ID. Unknown/nonconforming IDs are
omitted rather than truncated. No query, key, raw headers, response body, source
title/URL, photo or exception text is included in diagnostics/log entries.

Stages: `configuration`, `provider_resolution`, `dispatch`, `response`, `parse`.
Stable codes: `configuration_invalid`, `credential_missing`, `model_unverified`,
`provider_resolution_failed`, `request_rejected`, `authentication_failed`,
`access_denied`, `model_not_found`, `rate_limited`, `provider_unavailable`,
`redirect_rejected`, `transport_error`, `timeout`, `response_invalid`,
`response_incomplete`, `response_refused`, `search_missing`, `citations_missing`,
`citation_invalid`, `source_invalid`, `malformed_json`, `schema_invalid`,
`identity_mismatch`, `claim_invalid`, `matched`, `ambiguous`, `no_results`,
`connection_verified`. Clients should handle unknown future codes with a neutral
fallback; a diagnostic never authorizes automatic replay. `dispatch_started`
does not establish acceptance or billing. Known HTTP errors after research
dispatch retain conservative `unknown_outcome` semantics.

`POST /api/llm/profiles/{name}/test` keeps its old response fields `success`,
`message`, `model_info`, adding optional `diagnostic` and `research_result`:

- Default `test_kind: "connection"` uses **one read-only GET** to the official
  OpenAI `/v1/models/{exact-model}` endpoint for approved official destinations.
  It validates authenticated exact model metadata access only, not generation,
  billing or web search. It bypasses SDK provider inference without rewriting
  the model ID. Other providers retain explicitly labelled legacy completion tests.
- Explicit `test_kind: "research"` requires `identity` with a public
  manufacturer/part-or-model contract for the diagnostic test dialog. The UI must require an explicit
  cost-confirmed action. The named profile is tested even when Off, through the
  same bounded adapter; testing does not change any settings, canonical research
  selection, capture role or inventory. Success is true only for validated
  `matched` or `no_results`; the latter means request completed without results,
  not product verification. Ambiguous, incomplete and unknown results are false.
- Existing key/destination restrictions also apply to unsaved overrides. No
  save, enable, editor-open or navigation triggers either test. Test messages
  should remain visible until dismissed or replaced.

Exact `gpt-6.1-terra` metadata permits Responses web search and research reasoning
`none`, `low`, `medium` (provider default), `high`, `xhigh`, `max`. Catalog absence
does not block this documented model. Literal `gpt-6-terra` is not renamed or
treated as documented; a connection test can check its literal access, but
research eligibility remains unverified unless supported metadata is available.

### First-party references inspected

- [Responses create schema](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Web search output and citations](https://developers.openai.com/api/docs/guides/tools-web-search?api-mode=responses)
- [Citation formatting](https://developers.openai.com/api/docs/guides/citation-formatting)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [GPT-6.1 Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra)
- [Retrieve model](https://developers.openai.com/api/reference/resources/models/methods/retrieve)

Offline mock-HTTP tests establish routing/validation, not model access or live
search quality. A separate actual-provider public product-family reference-photo probe
returned seven suggestions and one citation; this is not an owned-item photo or
fitment acceptance claim. No further paid calls are required for the image gates.

Select proposals individually. Current values (including intentionally empty values) remain unchanged until adoption. Only unambiguous native TEXT fields with server-controlled meanings are eligible: Manufacturer/Hersteller, Part number/Part number (OEM)/Teilenummer, Model number/Modellnummer, Specifications/Technical specifications/Technische Daten, and coarse Vehicle family/Fahrzeugzuordnung. The latter is an unverified family/model suggestion only, not VIN-, engine-, model-year-specific compatibility or installation approval. Core title and description proposals are separately editable and selectable too. MSRP never maps to purchase price. Unrelated/native sibling field IDs are preserved. Changed drafts/templates reject adoption. Draft reviews expire after 15 minutes and do not survive a server restart; capture/save still works.

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
