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

Exact lock versions reviewed: `@sveltejs/kit` **2.70.3**,
`@sveltejs/adapter-static` **3.0.10**, `@sveltejs/vite-plugin-svelte` **7.3.1**,
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

The runner executes the real `npm audit --package-lock-only --json`, preserving
stdout (`npm-audit.json`), stderr, actual exit status and the policy result. It
prints the raw report even on failure. A nonzero npm exit is never automatically
ignored. Exit 1 is accepted only with a complete matching findings report;
transport/error JSON, other exits, malformed/truncated/duplicate-key JSON,
unreconciled counts, unknown fields/links/advisories, cycles, higher severity and
missing evidence fail closed. Exit 0 with a valid complete zero-findings report
is honestly reported as zero findings, with no exceptions used.

`frontend-audit-policy.json` binds the entire lock and manifest, Svelte/Vite/TS
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
uploaded even on failure. Branch/environment protection and publication/retry
identity logic are unchanged. Hosted CI success must still be independently
verified; local results are not publication approval.

## Current blocker discovered during implementation

A fresh registry audit additionally reports these **unapproved moderate** findings:

- [GHSA-jf9x-2fg2-hx4w](https://github.com/advisories/GHSA-jf9x-2fg2-hx4w):
  adapter-static prerendered paths interpreted as regular expressions in Vercel
  route configuration; audit suggests adapter-static 3.0.11 as the fixed floor.
- [GHSA-mw6w-2fmv-pvw3](https://github.com/advisories/GHSA-mw6w-2fmv-pvw3):
  Kit adapter-node unhandled URIError after reroute of malformed pathnames;
  audit suggests Kit 2.70.4 as the fixed floor.

These are registry statements, not independently established application
exploitability or tested remediation. **The current lock remains blocked.** No
additional exception or dependency update was authorized or performed. A narrow
patch review, if authorized separately, must reassess the new lock and context
before rebinding the original exceptions. Do not broaden this policy to pass CI.

## Offline evidence

`tests/fixtures/frontend-audit/reviewed.json` is the original public npm response
containing only the approved findings. `new-moderate.json` is the fresh public
registry response proving that additional findings block. Neither fixture has
private inventory, addresses or credentials. These fixtures are offline test
inputs, not substitutes for the runner's current live registry result.

Tests cover acceptance, honest zero findings, new findings on the same packages,
identity/severity changes, schema/count errors, graph cycles/dangling links,
source/lock/config changes, raw error/truncation/duplicate keys, actual process
status preservation and required candidate-workflow integration.
