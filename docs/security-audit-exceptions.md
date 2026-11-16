# User-approved frontend audit exceptions: private usability pilot

## Decision and boundary

The user explicitly accepted **only the five advisories below** for the **private
usability pilot**: three previously approved **low** findings and, separately for
0.5.1, **GHSA-3r8g-jcqq-3p5j (high)** and **GHSA-6cf5-gc4q-fm3x (moderate)**.
Consent to continue applies to these two exact new findings, not all findings or
a raised severity threshold. This is accepted
risk, not a claim that the application is unexploitable or that raw npm audit is
clean. Private/LAN-only reachability reduces some exposure; it is not complete
protection against malicious pages, clients, compromised peers or build inputs.

There is **no fixed 30-day expiry**. This authorization is phase-bound, not a blanket
or indefinite waiver. Successful usability-pilot acceptance triggers the planned
framework migration and a fresh security review before moving beyond this phase.
Stop relying on these exceptions and review again when:

- the pilot is accepted or the intended use moves beyond the private pilot;
- network exposure, trust boundaries, input provenance or deployment context changes;
- dependencies, the reviewed frontend source/configuration, vulnerable API usage,
  or advisory identity/severity changes;
- a new security finding or contrary applicability evidence appears.

No stable promotion, production deployment or paid AI usage is authorized here.
Source/test-image publication remains subject to its separately approved gates.
Human review must enforce the real-world phase/exposure triggers: CI cannot know
whether a user has accepted the pilot or changed a network outside this repository.

## Exact accepted findings

| Advisory and public source | Reviewed rationale (not proof of absence of risk) |
| --- | --- |
| [GHSA-pfhg-q3qv-9q6r / CVE-2026-114060](https://github.com/advisories/GHSA-pfhg-q3qv-9q6r) | Kit enhanced-form redirects may navigate off-origin. The reviewed app has no `use:enhance` usage. The static SPA uses backend APIs; no vulnerable enhanced-action path was demonstrated. Kit still contributes shipped client code: this is not dismissed as dev-only. |
| [GHSA-27mw-82g8-phjj / CVE-2026-114061](https://github.com/advisories/GHSA-27mw-82g8-phjj) | Untrusted `setHeaders` cache-control can enter prerendered HTML. The reviewed source has no `setHeaders` usage; no untrusted prerender input path was demonstrated. |
| [GHSA-gcqx-w48m-w2h4 / CVE-2026-93753](https://github.com/advisories/GHSA-gcqx-w48m-w2h4) | deepmerge is used by the Svelte build plugin to merge local configuration, not a demonstrated runtime untrusted-request path. The [official CNA CVE record](https://cveawg.mitre.org/api/cve/CVE-2026-93753) is REJECTED because it does not describe a security vulnerability. GitHub/npm still report the advisory; it is explicitly accepted, not silently erased or called withdrawn. [Maintainer discussion](https://github.com/TehShrike/deepmerge/issues/273) is supplementary, not the authority for rejection. |
| [GHSA-3r8g-jcqq-3p5j / CVE-2026-128120](https://github.com/advisories/GHSA-3r8g-jcqq-3p5j) — **high** | DoS while parsing experimental remote-function form data. The reviewed static SPA does not enable `experimental.remoteFunctions` or import `$app/server`; the Python runtime image serves the static frontend, not a SvelteKit server or remote-function endpoints. This is contextual non-use, not a general claim that the vulnerable package is safe. |
| [GHSA-6cf5-gc4q-fm3x / CVE-2026-128119](https://github.com/advisories/GHSA-6cf5-gc4q-fm3x) — **moderate** | Private `query.batch` function collisions. The reviewed source has no `query.batch` or `$app/server` imports and no enabled remote functions. Static adapter and disabled SSR retain the reviewed context; changing usage or deployment requires reassessment. |

Exact lock versions reviewed: `@sveltejs/kit` **2.70.4**,
`@sveltejs/adapter-static` **3.0.11**, `@sveltejs/vite-plugin-svelte` **7.3.1**,
`deepmerge` **4.3.1**. Four affected-package entries propagate **five** unique
advisories in the current 0.5.1 report: three low, one moderate and one high. npm
counts these packages as **three low and one high**, because the Kit node includes
both the moderate and high direct advisories. The historical reports had three
underlying low advisories. Acceptance is **not by package name
alone or by severity threshold**. The checker walks every `via` edge and matches
full direct advisory objects (ID URL, numeric source, package, severity, range,
title, CWE and CVSS) against `frontend-audit-policy.json`.

## Fail-closed implementation

Run from the repository with Python and the pinned Node available:

```sh
bash scripts/audit-frontend.sh /absolute/path/to/audit-evidence
```

The runner executes the real `npm audit --package-lock-only --json` with fixed
`--include=dev --include=optional --include=peer`,
`--registry=https://registry.npmjs.org/` and `--audit-level=low`. Explicit includes
win over inherited `npm_config_omit`, `NODE_ENV=production` and project `.npmrc`
omission settings. Inventory totals alone do **not** prove audit coverage: npm
can omit dev findings while reporting the same full dependency totals. The
registry is pinned to the public advisory authority reviewed here; the low exit
threshold preserves exit 1 for the approved low findings even if caller config
requests a higher threshold. Neither setting expands the approved advisory set.
The runner accepts only an output directory, never caller-supplied npm arguments.
It preserves stdout (`npm-audit.json`), stderr, actual exit status and the policy result. It
prints the raw report even on failure. A nonzero npm exit is never automatically
ignored. Exit 1 is accepted only with a complete matching findings report;
transport/error JSON, other exits, malformed/truncated/duplicate-key JSON,
unreconciled counts, unknown fields/links/advisories, cycles, changed severity and
missing evidence fail closed. Exit 0 with a valid complete zero-findings report
is honestly reported as zero findings, with no exceptions used.

`frontend-audit-policy.json` binds the entire lock and manifest, the tracked
`frontend/.npmrc` (reviewed contents: only `engine-strict=true`), Svelte/Vite/TS
configuration and every file under `frontend/src` by SHA-256, including exact
source inventory. Source additions/deletions/changes (even harmless changes)
therefore require deliberate re-review before exceptions can apply. This is
stronger than searching for two API spellings, but is not formal reachability
proof. Dependencies are assessed from the lock, not a possibly stale installed
`node_modules`. Changes to build orchestration outside the bound paths, external
inputs and deployment context still require human review. Do not regenerate
fingerprints merely to obtain a green gate. Review the changed context first;
any broader exception needs explicit user approval.

Registry fix suggestions may evolve without becoming accepted advisories; their
schema is checked but they are never executed. The checker processes all reported
packages and reconciles npm's affected-package counts, rather than conflating
those counts with the number of unique advisory IDs. After exact direct-object
matching, the package severity must equal its highest reported direct severity;
the reviewed propagation-only package nodes remain low. This is not a generic
high/moderate allowance for those packages. Removal of a finding can
reduce the accepted set; it cannot introduce an unknown cause.

Python `pip-audit --local --skip-editable` remains fully blocking and unchanged.
The existing `audit` job identity remains, runs on every PR (no path filters), and
runs weekly/manually. Validation also calls that same audit workflow at the exact
candidate SHA; `release-gate` now requires its success. Raw/policy artifacts are
uploaded even on failure as `frontend-audit-${{ github.job }}-${{ github.run_attempt }}`,
without overwrite, so reruns preserve earlier audit evidence. Only audit evidence
is attempt-qualified: `release-image`, image sealing and same-run publication
identity remain intentionally immutable and unchanged. Branch/environment
protection is unchanged. Hosted CI success must still be independently
verified; local results are not publication approval.

## Narrow patch remediation and renewed review

The user separately authorized only Kit 2.70.3 → 2.70.4 and adapter-static
3.0.10 → 3.0.11. These patch releases remediate the previously blocking,
**unapproved moderate** findings:

- [GHSA-jf9x-2fg2-hx4w](https://github.com/advisories/GHSA-jf9x-2fg2-hx4w):
  adapter-static prerendered paths interpreted as regular expressions in Vercel
  route configuration; audit suggests adapter-static 3.0.11 as the fixed floor.
- [GHSA-mw6w-2fmv-pvw3](https://github.com/advisories/GHSA-mw6w-2fmv-pvw3):
  Kit adapter-node unhandled URIError after reroute of malformed pathnames;
  audit suggests Kit 2.70.4 as the fixed floor.

Fresh GitHub advisory API responses confirm these fixed floors on the existing
major branches. The npm package source diffs confirm literal escaping of Vercel
route regex paths and decoding the original pathname inside the guarded reroute
block. LAN/static deployment is not used as an exemption for either finding.
The Kit patch additionally changes client route-resolution import origins,
server fetch redirect handling, preview path containment and prerender header
escaping; it is not merely a version-label change.

The renewed review found:

- The lock changes only the two requested packages (version, resolved URL and
  integrity), plus their root manifest declarations. All other package objects
  and dependency counts are unchanged; no Python dependencies changed.
- Every frontend source/configuration file matches the prior reviewed hashes.
  `frontend/src` still has no `use:enhance` or `setHeaders` calls. Static adapter
  fallback remains `index.html`, with root `ssr = false` and `prerender = false`.
- Enhanced-form redirection remains an accepted low finding; the patch does not
  change the forms implementation. Shipped Kit client code remains in scope.
- Kit 2.70.4 now escapes the prerender cache-control meta content in
  `src/runtime/server/page/render.js`. Nevertheless, GitHub/npm still report
  GHSA-27mw-82g8-phjj for `<3.0.0`; retain the existing explicit low exception,
  not a claim that the registry finding vanished or a new exception.
- Plugin 7.3.1 and deepmerge 4.3.1 are unchanged. Plugin
  `src/utils/options.js` merges local defaults/Svelte configuration/inline
  options during configuration. No app import or untrusted runtime deepmerge
  path was found. The official CNA record remains REJECTED while npm remains
  active; this accepted-risk distinction is unchanged.

Only the manifest/lock hashes and the two exact version bindings were updated;
all advisory objects, remaining hashes and inventory guards are unchanged.
Fresh real npm audit reports **four low affected packages propagating exactly
three approved advisory IDs**, with no moderate/high/critical findings. Its exit
is still **1**; the policy accepts the reviewed exceptions, **not a clean raw
audit**. Historical new-moderate evidence must still fail for unapproved severity.
Local verification covers npm ci, frontend checks/build, Chromium browser tests,
Python checks/tests/audit and real browser → Companion → isolated Homebox with
synthetic provider boundaries. This is not hosted CI or publication approval.
Independent combined review is required before push, merge or image publication.

## Offline evidence

`tests/fixtures/frontend-audit/reviewed.json` is the original public npm response
containing only the approved findings; it is retained byte-for-byte as historical
evidence. `new-moderate.json` is the historical public registry response proving
that additional findings block. `patched-reviewed.json` is the actual public
response collected against Kit 2.70.4 / adapter-static 3.0.11 before the two new
0.5.1 findings. `pilot-051-reviewed.json` preserves the actual full-coverage raw
report with the five explicitly accepted findings. Both snapshots remain tested;
new mutation cases reject changed IDs/severities and inconsistent aggregation.
Historical version bindings cannot authorize the patched graph. These fixtures
have no private inventory, addresses or credentials and are offline test inputs,
not substitutes for the runner's current live registry result.

## Research settings and entry-point source reassessment

The next-version research UX changes were reviewed against the three accepted
low advisories before rebinding source hashes. The changes add an authenticated
JSON settings read/write UI and fixed local navigation fragments, not SvelteKit
form actions. They introduce no `use:enhance`, `setHeaders`, dynamic HTML or
runtime deepmerge imports. Profile names, reasons and model names use escaped
Svelte text; keys are absent from the new response and browser payloads. The
summary control preserves the existing failed-row editor and excludes written,
partial and unknown rows. Opening research only reads capabilities; paid lookup
and field adoption remain separate explicit actions.

Only the reviewed changed source hashes and the new ResearchSection source entry
are rebound. Package versions, manifest/lock/.npmrc bindings, all three exact
advisory objects, raw historical audit fixtures and the fail-closed runner/checker
are unchanged. This is a source-context reassessment for the same private pilot,
not another waiver, a clean raw audit, independent acceptance or publication
approval. The remaining capture/navigation/undo work requires its own reassessment.

The separately requested About-section project and release links now target the
maintained `bennyb21/homebox-companion` fork. Both are constant HTTPS URLs with
the existing `noopener noreferrer` policy; upstream attribution and LICENSE
remain unchanged. That exact AboutSection source hash is also deliberately rebound.

## Integrated 0.2.0 capture and model-configuration reassessment

The combined capture and model UI source at integration input
`a8bb2b126c9f85767299dd3c6fd0d6e127aa2058` was reviewed before updating the
bindings for the private **0.2.0** candidate. This supersedes the pending
capture reassessment above; it is implementer integration review, not the
required independent acceptance.

- Capture grouping, retained drafts, undo, step navigation and stale-analysis
  confirmation use local state/IndexedDB and existing JSON/upload APIs. The new
  navigation targets are fixed local routes, not enhanced form redirects.
  Submission checkpoints and written/uncertain-row restrictions remain in scope.
- Model settings use ordinary prevented-submit handlers and authenticated JSON
  APIs. Model/profile names, credential provenance and reasoning options render
  as escaped Svelte text, not new dynamic HTML. Shared credentials are represented
  by references and availability metadata, not returned secrets. No new provider
  request is initiated by saving, enabling research or opening a research editor.
- Explicit source search and review found no `use:enhance`, `setHeaders` or
  deepmerge imports under `frontend/src`. This is reviewed evidence, **not a
  formal absence or reachability proof**. Existing sanitized chat/log HTML paths
  were not changed. Static-adapter `index.html` fallback, `ssr = false`,
  `prerender = false` and Svelte/Vite configuration are unchanged.
- Plugin 7.3.1 `src/utils/options.js` still invokes deepmerge for local defaults,
  loaded Svelte configuration and inline/build options. The reviewed new capture
  and settings inputs do not feed that build-time configuration. No new untrusted
  runtime merge path was demonstrated; compromised build inputs remain a risk.

The deliberately renewed bindings cover sixteen changed source files: settings
API types; StepIndicator; About/LLMProfiles/Research sections; scan persistence and
serialization; route guards; capture/review/scan workflows; and layout, capture,
location, review and summary routes. Two more bindings cover frontend manifest
and lock **project-version metadata only** (0.2.0). Structural comparisons retain
all dependency package objects unchanged, including exact reviewed package
versions. Python's local project lock entry and Docker version default also move
to 0.2.0; this does not modify or republish released 0.1.0.

The integration rerun also exposed a queued-autosave edge case: a page-hide flush
could overwrite the recoverable confirming checkpoint with a terminal draft after
an uncertain submission. A deterministic failing regression and the unchanged
browser recovery scenario now cover a narrow terminal-state guard in `_doPersist`.
That final scan-workflow hash was reviewed and rebound again; the guard introduces
no form, header, rendering, merge or provider-request path.

The three advisory objects, phase, dependency counts, source inventory,
configuration hashes, `.npmrc`, checker/runner guards and all historical audit
fixtures are unchanged. A new actual full-coverage npm runner report is retained
with private integration evidence; it is not substituted into historical
fixtures. Raw exit **1** with the same three low advisories is accepted risk,
**not zero findings**. No new exception or expiry is introduced. Successful
private-pilot acceptance still triggers framework migration and fresh review.
Independent combined review and hosted candidate/image gates remain required
before separately authorized publication.

Tests cover acceptance, honest zero findings, new findings on the same packages,
identity/severity changes, schema/count errors, graph cycles/dangling links,
source/lock/config changes, raw error/truncation/duplicate keys, actual process
status preservation and required candidate-workflow integration.

## Integrated 0.3.0 research and usability reassessment

The combined source from integration input
`a1cba77ce6f6ed369247101e2fa7da806de017d1` was reviewed against the same three
accepted contexts before rebinding. This is implementer review for a PRIVATE,
unpublished candidate, not independent acceptance or verified live search quality.

- Profile editor and explicit test forms prevent ordinary submission and use
  authenticated JSON API calls. No enhanced form action or `use:enhance` was added.
  Return links are limited to fixed review/research routes; profile names are URL
  encoded and cannot supply an arbitrary navigation destination.
- Model names, diagnostics, source titles and eligibility messages use escaped
  Svelte text. The copyable diagnostic textarea selects only contract fields;
  arbitrary provider bodies are not rendered. Existing sanitized chat/log HTML
  paths are unchanged. No `setHeaders` or new prerender input path was found.
- The shared Switch, capture mode text, profile selection and direct edit controls
  do not feed build configuration. Plugin 7.3.1 still merges local Svelte/default/
  inline options with deepmerge. No runtime deepmerge import was introduced.
  This source review is not a formal reachability or exploit-absence proof.
- Profile tests are explicit operations: official OpenAI access uses read-only
  model metadata; the separately confirmed research test uses the named profile
  without assigning it. Save/enable/navigation must initiate no provider request.

Thirteen bindings change: frontend manifest and lock root version metadata;
new research API types, DiagnosticDetails, ResearchProfileSummary and Switch;
settings API, ProductResearch, AI Models and Research settings; capture, research
and settings routes. The complete source inventory includes the four new source
files. All third-party npm package objects and Python lock package objects remain
structurally identical to released 0.2.0. Only the local project becomes 0.3.0.

All three advisory objects, affected package versions, dependency counts, phase,
configuration/.npmrc bindings, historical raw fixtures and no-retry audit runner
remain unchanged. Raw npm exit **1** for these exact low findings remains accepted
risk, not zero findings. New findings remain blocking. No new waiver or expiry is
introduced; successful private-pilot acceptance still triggers framework migration
and fresh review. Released 0.1.0/0.2.0 artifacts remain immutable. Independent
review and hosted source/image gates precede any separately authorized publication.

## Integrated 0.3.0 attachment recovery reassessment

The attachment source integrated at
`96ff05a71289550130c3ea12a5937109f3cd3527` was explicitly reviewed against the
same three accepted contexts. Thirteen changed/new bindings are renewed: the API
client and items contract; new AttachmentRecovery component; SessionExpiredModal,
AccountSection and bootstrap logout boundaries; serialization and scoped session
persistence; submission and scan workflows; location, summary and success screens.

- Multipart upload remains an authenticated backend API operation, not an enhanced
  SvelteKit form action. Receipt validation and removal of auth/upload replay add
  no `use:enhance` path. Reset/navigation uses existing fixed local routes. The
  recovery link uses the configured Homebox base and an encoded known entity ID,
  with `noopener noreferrer`; original-photo download is a local File data URL,
  not an arbitrary server-supplied attachment URL.
- Names, slot state, filenames and known IDs render as escaped Svelte text, not
  dynamic HTML. Scoped IndexedDB records retain original photos and receipt
  metadata, not raw credentials. No `setHeaders`, prerender data input or runtime
  deepmerge import is introduced. Logout retention does not relax API identity
  or collection admission. Existing sanitized HTML paths are unchanged.
- These runtime recovery inputs do not feed plugin build configuration. The
  unchanged plugin/deepmerge local-configuration context remains accepted risk,
  not a proof that exploitation is impossible. Source searches and inspection
  are not formal reachability evidence.
- Newly uploaded Homebox attachment filenames visibly include the technical
  unique suffix; originals keep their names in local recovery. No existing names,
  image-quality controls or thumbnail behavior are changed by this integration.

Only these thirteen source hashes/inventory entries change (one new component).
All advisory identities/objects, package versions, dependency graph/counts,
manifest/lock/configuration bindings and historical raw audit fixtures remain
unchanged. Exactly GHSA-pfhg-q3qv-9q6r, GHSA-27mw-82g8-phjj and
GHSA-gcqx-w48m-w2h4 remain accepted at low severity for this same private pilot,
with no new waiver or expiry. A fresh full-coverage raw npm audit exits **1**;
the existing policy accepts those findings, not zero findings. Successful pilot
acceptance still triggers framework migration and fresh review. This is scoped
integration review, not a substitute for the parallel independent guard review
or the subsequent hosted image gates. Production source is unchanged from the
pinned review candidate.

## Guard review fix-cycle source reassessment

Before rebinding the guard corrections based on `c017404e456569a40adfff9cabc799199d1c7094`,
the seven changed production frontend files were reviewed against each accepted
low-advisory context: SubmissionService, ScanWorkflow, sessionPersistence,
AttachmentRecovery, and the review, summary and success routes.

- Run ownership, receipt consistency and exact save acknowledgement use existing
  local state/IndexedDB and authenticated APIs. They add no enhanced form action,
  `use:enhance`, arbitrary redirect destination or multipart retry. The review
  navigation hook still awaits persistence, now discarding its boolean result.
- Unknown success-page reloads use neutral escaped text and an explicit same-scope
  Resume action after verified authentication; its destination is fixed `/summary`.
  Recovery retains original downloads and the configured/encoded Homebox link.
  Invalid duplicate slot declarations no longer serve as UI keys. No dynamic HTML,
  `setHeaders`, prerender input or new external URL source was added.
- These runtime inputs do not feed build options. Svelte/Vite configuration,
  static fallback, plugin 7.3.1 and build-time deepmerge 4.3.1 are unchanged.
  Source inspection is not a formal absence-of-exploit or reachability proof.

Only those seven changed source hashes are rebound; no source inventory addition.
The three exact low advisory objects, dependencies, manifest/lock/config hashes,
phase, expiry policy and historical raw reports are unchanged. This remains the
same private usability pilot and accepted risk, not a clean raw audit or a new
exception. Independent corrected-candidate review and actual built-image gates
remain separate requirements before any authorized publication.

## 0.4.0 whole-item research reassessment

Independent scoped review accepted the runtime delta at
`623ad7abd0fc44c4ae3838aa21baf9950bd62782`: ProductResearch, saved research page,
review adoption callback and research API types, together with the provider/parser,
draft/job API, worker and bounded native-photo reader. Suggestions render as escaped
Svelte text/textarea values, not raw HTML. Provider links are validated HTTP(S)
display metadata, distinct from suggestion admission. Explicit dispatch/adoption,
no automatic inventory writes, source/photo snapshots and stale-state guards remain.
Native photo fetches are same-origin, bounded and reject redirects/path-shaped IDs.

No enhanced form action, `use:enhance`, `setHeaders`, dynamic HTML or new build-time
input path was introduced. The static build configuration, npm settings and
plugin/deepmerge context remain unchanged. This is a scoped review, not a formal
proof that exploitation is impossible.

Exactly six bindings are renewed: those four frontend runtime files and the two
manifest/lock root-version changes to 0.4.0. Third-party dependency objects are
unchanged. Advisory objects, package versions, graph/counts, phase and historical
raw fixtures remain unchanged: the same three low advisories are accepted risk,
not a clean raw audit. New findings remain blocking; no exception is added or
extended. Successful usability acceptance still requires the deferred framework
migration and fresh review before leaving this test pilot. Version 0.3.0 and all
older published artifacts remain immutable. Required hosted gates and protected
same-artifact publication are still mandatory.

## 0.4.1 research-quality reassessment

The parent independently reviewed runtime changes through
`120e83ac0428325d5b8ba8549bfbaf07fcba5202`. The exact bound frontend delta was
reviewed again before rebinding: research/settings API types, ProductResearch,
LLMProfilesSection, and research/review routes. Native manufacturer/model patches
use the existing explicit, edited and selective adoption flow. The profile test
sends escaped free-text product context through the same authenticated endpoint.
Removed per-proposal notices do not add a rendering or network path; sources and
genuine ambiguity remain visible.

These six files introduce no raw HTML, enhanced form action, `use:enhance`,
redirect target, `setHeaders` or build-time input. Static build configuration,
plugin/deepmerge context and npm configuration are unchanged. This is scoped
source review, not a formal proof of exploit unreachability.

Only those six source bindings and the two manifest/lock root-version bindings
change. Third-party dependency objects, advisory objects, graph/counts, phase
and historical raw fixtures are unchanged. The same three low advisories remain
accepted risk for the private usability pilot, not zero findings; no new waiver
or advisory is accepted. New findings still block. Successful usability acceptance
still triggers framework migration and fresh review before leaving the pilot.
Published 0.4.0 remains immutable; existing hosted and protected image gates apply.

## 0.5.0 browser-language and compact-research reassessment

The parent independently reviewed runtime through
`df42f2ec8569eb6d462d31cbdda52da3669ea79f`. The release review inspected the
changed frontend security contexts before rebinding:

- Translation calls replace app-owned text, labels, placeholders and error prose
  in routes, components, API wrappers, stores and workflows. The catalog is local
  typed data; interpolation returns strings rendered through Svelte text/attribute
  escaping. It does not feed HTML, URLs, request destinations or build options.
  Existing ChatMessage sanitized-markdown rendering and LogViewer rendering are
  unchanged; translations are not routed into these HTML sinks.
- Locale detection accepts only `de`/`en`, falls back to English and tolerates
  blocked browser storage. The new state writes only `hbc.ui-language` and document
  `lang`; the fixed Settings selector does not dispatch requests or modify AI
  output language, identifiers, inventory values or custom-field names.
- ResearchProposals and autosize use escaped labels, input/textarea values and
  numeric measured height. Received-value grouping retains original indices;
  adoption remains explicit with existing scope/staleness checks. ResearchNotice
  and collapsed diagnostics are presentation changes, not new request paths.
  Source aggregation deduplicates existing server-validated HTTP(S) citation
  metadata; links retain `noopener noreferrer`. ResearchProfileSummary retains a
  fixed Settings route and restricted return targets, removing the extra edit link.
- No `use:enhance`, enhanced form action, `setHeaders`, new raw-HTML sink or
  untrusted prerender/build configuration input was introduced. The static SPA,
  Svelte/Vite/TS configuration, `.npmrc`, plugin and deepmerge contexts are unchanged.
  This is scoped source review, not a formal proof of exploit unreachability.
- Hosted WebKit exposed synchronous ResizeObserver geometry writes in autosize.
  The release correction coalesces them in requestAnimationFrame and cancels the
  pending frame on teardown. Only the existing autosize binding is renewed again;
  no data sink, exception or browser-error filtering is added. The unchanged DE/EN
  mobile browser tests retain their no-unhandled-errors assertion.

Exactly 75 changed existing source hashes and the two frontend manifest/lock
root-version hashes are renewed. Seven new inventory bindings cover autosize,
ResearchNotice, ResearchProposals, LanguageSection and the three i18n files.
Third-party dependency objects, exact advisory objects, severity/graph/counts,
phase and historical raw fixtures remain unchanged. The same three low advisories
remain accepted findings for the private usability pilot, not a clean raw audit.
No new exception, expiry extension or policy bypass is granted. Praise of one
example is not full pilot acceptance: successful usability acceptance still
triggers framework migration and fresh review before leaving the pilot. Published
0.4.1 and older images remain immutable; existing hosted and protected gates apply.

## 0.5.1 selection and technical-description reassessment

The release reviewer independently inspected the runtime delta through
`0c1e1934366621d2bc4081b03b27d00a14061bb4` before renewing bindings.
ResearchProposals changes only local numeric selection state, including hidden
unchanged proposals; it preserves edited values and original adoption indices.
The checkbox is disabled during adoption, and selection itself makes no request.
Its two catalog labels use existing escaped Svelte text/attributes. The shared
technical-description instructions and default preference change prompt text,
not routes, schemas, model settings or persisted user preferences.

No enhanced form action, `use:enhance`, `setHeaders`, raw-HTML sink, new URL source
or untrusted build input was added. Static SPA configuration, sanitizers and the
plugin/deepmerge context are unchanged. This is scoped source review, not formal
proof of exploit unreachability.

Only the two affected existing frontend source bindings and the manifest/lock
root-version bindings are renewed. Dependency objects, phase, configuration and
historical fixtures are unchanged. The initial full-coverage release audit then
correctly blocked the two newly published remote-function advisories above.
After reviewing those exact advisories and the unchanged static/Python runtime
context, the user explicitly approved those **two additional exceptions only**.
Their complete direct objects are added without changing package versions,
coverage flags, registry, raw exit handling, severity threshold or protections.
The checker validates every direct identity before reconciling package severity;
the high Kit package does not hide its moderate direct advisory. Unknown findings,
changed severity, incomplete reports and unreviewed source/configuration still
block. No dependency migration or additional runtime change is part of this
exception update. All previous fixtures remain historical evidence.

A passing policy with raw npm exit **1** means **five accepted findings**, not a
clean audit. No arbitrary expiry is introduced: the exceptions remain limited to
the same private pilot, and changes in usage, source, dependencies or deployment
trigger renewed review. Framework migration remains due after successful
usability-pilot acceptance. Published 0.5.0 remains immutable; required hosted and
protected gates still apply.
