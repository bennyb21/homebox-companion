# Research and capture UI

## Photo grouping

The **One item per photo** sliding switch starts off for a new session. Off means **Multiple photos of one item**: all selected views are grouped and analyzed together. On means one item per photo, not object splitting inside each image. The visible item/photo count reflects the groups. Resuming a draft retains its mode. Existing analysis must be explicitly discarded before changing inputs; navigation alone never reanalyzes.

**Saved photo quality — not AI input** expands storage-quality and close-up guidance. Changing stored photo quality does not promise more detail in AI input.

## Which research model is used?

**Research uses: profile — model** comes from the canonical saved research assignment, not from a profile's name. It is shown in Settings and beside item lookup. **Choose research profile** opens Settings; **Edit active research profile** opens the central AI Models editor for that exact profile. **Return to item draft** returns to the retained review draft without starting research or confirming the item.

Settings always exposes the Research profile selector and **Edit selected profile** / **Create research profile**, even with only one eligible profile. An ineligible profile can be edited but cannot be enabled or saved as an active research selection. Actions wait for the central profile list to load. Profile changes received during a settings read trigger another read rather than leaving an old model displayed.

An existing Primary profile can also be selected for research without changing its capture role. Editing that shared profile's model affects both uses. To use a different research model, create a research-only profile; the editor defaults to Research and references an available shareable credential (or an available environment credential) without copying or displaying its key. Check the role and selection before saving. Merely editing or testing an Off profile does not activate it.

Model IDs are free text, preserved exactly. There is no automatic correction of model names. Reasoning options come from server metadata; absence of options does not diagnose an invalid key. Eligibility is not proof of account access. Technical reasoning/request-limit guidance is expandable.

## Explicit research and diagnostics

The neutral notice identifies the public model/part search inputs sent to OpenAI, possible API costs, and absence of automatic inventory changes. No serial-number attestation checkbox is required. Supported identifiers remain model number or part number. New requests **omit `identity_confirmed`**; they do not manufacture a `true` user attestation.

Research remains explicit. Per-field current/proposed values, evidence labels, and source links are retained. Adoption is available only for matched results; selected fields still require a separate adoption action. Existing stale-draft and write-readback guards remain.

Failures remain visible rather than disappearing after five seconds. The UI displays the server-curated explanation and stable code, plus expandable read-only, selectable/copyable diagnostic fields. It does not display arbitrary provider bodies or optional metadata. Legacy failures without a diagnostic have an unknown-cause explanation rather than guessing that a key is wrong. Incomplete, refused, no-result, and unknown outcomes are distinct. Unknown outcomes may have incurred costs and never trigger automatic retry.

## Tests are different tasks

- **Check API access** tests the named saved profile's access, not web research. The revised backend uses an exact-model metadata GET for official OpenAI profiles; other providers may retain a billable completion check. Read the returned message to see what passed.
- **Run research test** opens a dialog requiring a public model/part identifier and an explicit **Run paid research test** click. It tests the named profile even when Off, without assigning it or changing inventory. A completed no-results response is not a successful product match.
- Opening, saving, selecting, enabling, and navigation do not start either test. Only one profile test can run at a time, and test POSTs disable automatic authentication replay.

## Integration and verification boundary

The frontend requires the revised backend identity/test contract: optional safe `diagnostic` on research and test responses, optional `research_result` on profile-test responses, and `test_kind: connection|research` with structured identity for research. Incomplete/refused backend results may retain status `failed`; the UI recognizes `response_incomplete` / `response_refused` diagnostics. Older results without diagnostics remain readable. An old backend that requires `identity_confirmed` is not compatible with new lookup requests.

Browser tests use explicitly synthetic local API fixtures and blocked external requests. They verify UI behavior and request payloads, not a paid provider's behavior or a real backend integration. The isolated-Homebox fullstack research scenario is updated for the identity notice but must be run by the integration owner with the matching backend. No live research acceptance is implied.
