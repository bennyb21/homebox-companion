# User-approved frontend audit exceptions: private usability pilot

## Decision and boundary

The user explicitly accepted **only the three advisories below**, at their reviewed
GitHub/npm **low** severity, for the **private usability pilot**. This is accepted
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

Exact lock versions reviewed: `@sveltejs/kit` **2.70.4**,
`@sveltejs/adapter-static` **3.0.11**, `@sveltejs/vite-plugin-svelte` **7.3.1**,
`deepmerge` **4.3.1**. Four affected-package entries propagate three underlying
advisories in the original reviewed report. Acceptance is **not by package name
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
unreconciled counts, unknown fields/links/advisories, cycles, higher severity and
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
those counts with the number of unique advisory IDs. Removal of a finding can
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
response collected against Kit 2.70.4 / adapter-static 3.0.11; active acceptance
and mutation tests use this new snapshot and assert exact reviewed versions.
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
