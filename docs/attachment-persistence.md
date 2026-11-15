# Attachment persistence guard (private 0.3.0)

Homebox 0.27.1 can return HTTP 201 with unchanged entity detail after an attachment
save error. Companion does not treat that response as a successful photo upload.
This is a client safety boundary, **not a fix for Homebox's database error**.

## Upload contract

`HomeboxClient.upload_attachment` uploads once and returns a receipt dictionary;
`upload_attachment_typed` returns `AttachmentReceipt`. The native response's
outer `id` is the **entity ID**, never the newly created attachment ID. Library
call signatures remain compatible, including non-photo manual/warranty uploads;
return values now deliberately describe verification rather than raw native JSON.

Capture accepts optional multipart `attempt_id`, `slot`, and `original_filename`.
The capture UI supplies a random UUID and ordered slot only after checkpointing
the known item identity, original photos, manual fields and attempt in IndexedDB.
Legacy API/library callers may omit them; the server generates a correlation UUID.
Such callers must independently retain their originals and must not replay an
uncertain write. Companion's capture checkpoint is not a server-side job queue.

For the **actual bytes after server compression**, the shared client:

1. Freezes credential/group headers and freshly reads the exact entity.
2. Validates its identity, attachment-list schema and unique attachment UUIDs.
3. Rejects a marker already present before dispatch without another POST.
4. Uploads once, using `safe_original_stem__hbc_<UUID>.<extension>` as the native
   attachment name. No existing attachment is renamed; no bytes are changed to
   manufacture uniqueness. No `primary` mutation is added.
5. Requires one fresh row with the exact correlated title, intended type and MIME
   in the POST entity detail and a separate fresh GET of that same entity.
6. Streams the original blob from an internally constructed attachment-ID URL,
   with bounded size, exact length/MIME and SHA-256 checks. Returned storage paths
   are never followed and redirects are disabled.
7. Checks entity membership once more, then returns `verified`, `entity_id`,
   `attachment_id`, `attempt_id`, `slot`, `original_filename`, `title`,
   `mime_type`, `byte_length`, and `sha256`.

A preflight failure is `ATTACHMENT_NOT_DISPATCHED`. Any uncertainty after dispatch
is `ATTACHMENT_PERSISTENCE_UNCONFIRMED`; the capture route returns HTTP 409 with
safe known identifiers. Neither outcome authorizes automatic retry. Transport
loss between Companion and the browser also remains unconfirmed.

## Recovery

Attachment POSTs have neither the former three-attempt retry nor authentication
refresh/replay. The UI requires a matching typed receipt and checkpoints it
before advancing. Primary or additional uncertainty stops the remaining photos
for that item. **It never deletes or recreates the known item.**

Partial drafts retain original photos, order, manual fields, known item IDs,
per-slot attempt states and received receipts. Interrupted `in_flight` becomes
`unconfirmed` on recovery. Earlier drafts without photo-attempt fields remain
readable; a known created ID cannot become a retryable creation.

The summary/success view offers original-photo downloads and the known Homebox
item link. Repair is manual: inspect Homebox first because an unconfirmed photo
may already have committed. There is no background reconciliation or in-app
photo-retry action. Starting fresh explicitly warns before discarding recovery
records. Logout/expiry of authentication preserves the scoped draft. Uncertain
write drafts do not expire under ordinary seven-day cleanup, and another scan
cannot overwrite that scoped recovery row without an explicit discard.

## Limits

The unique suffix is visible in Homebox's **new attachment filename**. Original
filenames remain in the local draft/receipt. Browser storage can still be removed
by the user, browser eviction, disk failure or a reset outside Companion.

A receipt proves bytes and membership **observed at verification time**. It is
not atomic exactly-once delivery, an idempotency constraint, a future-persistence
promise, or a claim about power-loss durability. Another client may delete the
photo immediately afterwards. A manual repeat or deliberately copied marker can
still create duplicates. A lost receipt is not recreated by recompressing a photo
after restart. Existing compression/quality behavior is unchanged.

## Evidence boundaries

- `tests/test_attachment_persistence.py`: retained native false-201 replay,
  correlation/schema/readback failures and actual post-compression hashing.
- `tests/test_attachment_submission.py` with
  `frontend/tests/attachment-submission-probe.js`: production submission through
  actual ASGI and real Homebox transport; native grouped same-name/same-byte
  uploads and explicitly labelled false-201 fault injection.
- Frontend unit/browser tests: no replay/delete, durable attempts and receipts,
  recovery, original download, explicit discard and seven-day retention.

Run live tests only against disposable fixtures with
`TEST_HOMEBOX_VERSION=0.27.1`, and select `-m live`. Fresh artifact directories are
required. The native image remains pinned; no Homebox fork or deployment is part
of this change. Review/audit source bindings must be updated by the integrator
only after independent review of the combined candidate.
