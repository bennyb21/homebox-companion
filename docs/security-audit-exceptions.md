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

Tests cover acceptance, honest zero findings, new findings on the same packages,
identity/severity changes, schema/count errors, graph cycles/dangling links,
source/lock/config changes, raw error/truncation/duplicate keys, actual process
status preservation and required candidate-workflow integration.
