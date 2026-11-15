# Model profiles, research and credential sources

## Which model actually runs?

Settings → About → Show Details reports the effective **capture/chat model**, its source (saved Primary profile or environment when there is no Primary), credential source/availability, and separate Fallback and Research models. A saved Primary profile wins over the Compose `HBC_LLM_MODEL` / legacy model setting. Changing Compose does not replace saved profiles. Profile edits take effect on the next request without a restart and survive a restart.

Primary and Fallback are the capture/chat Router pool. Research never falls back through that pool. Research and Off profiles are not capture/chat deployments. A request already in flight retains the snapshot it began with; a save invalidates the Router for subsequent requests. Router construction and settings saves share a lock so a concurrent build cannot reinstall an obsolete credential snapshot.

A saved Fallback requires a saved Primary. Switching the existing Primary directly to Off is rejected; choose another Primary first. With neither role configured, empty or Off/Research-only settings use environment capture/chat defaults. Replacing or clearing Research retires its dedicated role to Off without creating a Primary. Deleting a Primary with remaining capture profiles retains the existing promotion behavior, but a dedicated Research profile is never automatically promoted.

## A different research model with the same key

1. Add an AI Models profile with a different name and desired model.
2. Choose **Research** for a dedicated research-only role.
3. Choose **Reuse another OpenAI profile's key** and the existing stored-key profile. No key is copied into the new profile. Alternatively choose **Environment key** when the key is supplied by environment configuration.
4. Optionally set **Research reasoning effort**. Save. Saving does not call a provider.
5. In Product research, explicitly enable research and confirm the selected profile. Enabling also makes no provider request. Each product search still needs its own explicit initiation.

The canonical research assignment is `research_profile_name`, not a second independent role selector. Choosing Research for a dedicated profile updates this assignment atomically; a previous dedicated Research profile becomes Off. Selecting a Primary or Fallback in Product research instead adds a **+ Research** assignment without changing its capture role. Changing a Primary/Fallback directly to Research is rejected with guidance to use the selector or create a dedicated profile. A dedicated assignment does not itself enable paid research.

Credential availability means a compatible configured value exists, **not** that billing, model access or the key's validity has been tested. This is the user's provider API key and billing account, independent of a Hermes/Codex subscription. The explicit Test connection action remains a provider call; it is not run on save or enable.

## Credential boundaries

- **Own stored key**: leave the password input blank when editing to retain it. The mask is a placeholder, never a submitted value. No API response includes stored or resolved secrets.
- **Environment key**: resolves the configured HBC key at request time only for a compatible OpenAI model and the official endpoint.
- **Profile reference**: a direct reference to another profile with its own stored OpenAI key. References to references (including cycles) are rejected. For an environment-backed source, choose Environment directly.

Sharing is deliberately limited to OpenAI model identifiers and exactly `https://api.openai.com/v1` (or unset/empty, meaning that official default). A trailing slash is not silently normalized. Other providers and custom gateways must have their own explicit credentials. Missing profile keys no longer implicitly inherit the environment or Primary key; missing credentials cannot fall through to an SDK ambient key. Official OpenAI capture/chat destinations are pinned explicitly instead of inheriting an SDK ambient base URL. SDK `os.environ/...` indirection in profile model/key/base fields is rejected in favor of the explicit credential source.

Renaming updates both research and credential references in the same transaction. Deleting a credential source is blocked until its dependents are changed. Deleting the selected research profile clears its assignment and disables research. Incompatible source-provider/base edits, invalid reasoning, and breaking an enabled research configuration are rejected before persistence. Disabling research first allows deliberate credential removal. Environment compatibility is rechecked at runtime, including after a deployment configuration changes.

Settings schema 4 preserves existing stored secrets without copying them. Legacy keyless official OpenAI profiles gain an explicit compatible environment reference; legacy compatible keyless Fallbacks reference a stored Primary key. Unsafe custom/cross-provider implicit inheritance is not preserved. New official OpenAI bootstraps reference the environment rather than persisting a duplicate key. Existing owned keys remain owned. No production environment file is changed by this migration.

## Reasoning is model- and transport-specific

The optional field is `research_reasoning_effort`, scoped to research only. Unset omits the `reasoning` parameter, using the provider default. The current verified allowlist covers the **exact** `gpt-6-luna` model: `none`, `low`, `medium`, `high`, `xhigh`, `max`. Other models can use provider default only until an exact model specification is reviewed; this is not a universal list assembled from different models.

Source: [official gpt-6-luna model specification](https://developers.openai.com/api/docs/models/gpt-6-luna). It lists medium as the default and requires `none` for Chat Completions function tools. Consequently capture/chat's exact `gpt-6-luna` / `openai/gpt-6-luna` deployments use `reasoning_effort=none` for Chat Completions compatibility. Research continues to use Responses and does not inherit that setting.

Research serializes `reasoning: {"effort": "..."}` through the real LiteLLM/SDK. The final HTTP boundary verifies model, reasoning, and budget parameters before dispatch. It keeps one POST to the fixed official Responses endpoint, required hosted web search, at most one tool call, 2400 output tokens, 45 seconds, and no retry/fallback. Reasoning tokens consume that same output budget: higher effort can leave incomplete output without visible results. No automatic budget increase is made.

## Offline verification

`tests/test_model_configuration.py` exercises authenticated settings mutations, atomic rejection, reference/rename/delete/selection lifecycle, schema migration, Router invalidation/concurrency, serialized vision/chat/research requests, and a fresh-process restart probe. Only synthetic credentials and injected SDK HTTP transports are used for acceptance. It does not establish live paid model access or search quality.

Browser coverage: `frontend/tests/browser/model-configuration.spec.ts` checks editable dedicated Research profiles, source references without a key payload, reasoning default/unsupported states, inline errors, readback disagreement, and effective display refresh. `HBC_BROWSER_TEST_ORIGIN=http://127.0.0.1:4187` can isolate Playwright from another worktree; the default remains port 4173. Audit source bindings must be reassessed after integration; this document does not waive that gate.
