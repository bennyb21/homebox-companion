# Native capture profiles

New captures default to **Automatic suggestion**. Choose an existing Homebox item type to override it, or explicitly choose **Default (no capture profile)** for the legacy workflow. Homebox remains the source of types, default-template references, field names, and defaults. Only native text templates are supported; non-text templates are rejected before item creation.

Automatic mode first discovers objects and proposes one existing type ID per object. Unknown or ambiguous proposals stop analysis with a request for explicit selection and retry; they never select the first catalog entry. Each object with template fields then gets a separate, schema-specific extraction pass. A manual type bypasses classification.

Model-call budget per image: manual = one detection call; automatic = one discovery/classification call plus one extraction call per object whose template has fields. Tests measure this using deterministic stubs, not paid inference. Real model accuracy and the ability to distinguish visually similar objects are not established by those tests. Photograph ambiguous objects separately.

## Review

Changing the type loads its current native default template. Existing values—including intentionally empty values—win over new defaults. Fields absent from the new template remain as additional text fields, with a notice; changing type never silently deletes them. Native references and values survive draft recovery.

AI correction and AI merge are deliberately unavailable for native-profile items. The review explains this and the client rejects these operations before a provider request. Edit the fields manually instead. The legacy correction workflow is unchanged.

## Interrupted submissions

Before sending a creation request, Companion checkpoints the draft and in-flight status. Returned IDs are checkpointed before attachment work. Repeated submission retries failed rows only, not known creations. Concurrent submissions/retries are guarded.

A lost response or recovered in-flight request requires manual reconciliation in Homebox rather than an automatic replay. These rows use the existing “needs attention”/partial-success presentation; that status is not proof that an unconfirmed item exists. Known partial creations retain their IDs. Incomplete drafts retain the original fields and photos even when the completion screen is shown. Starting a new scan explicitly resets that scan state.

A confirmed cleanup after a failed primary-photo upload permits a fresh creation; an unconfirmed cleanup does not. Automatic completion of missing attachments on an existing item is not implemented: reconcile the existing item in Homebox. This is not a server-side idempotency or cross-device exactly-once guarantee, nor a backup/restart-persistence guarantee.
