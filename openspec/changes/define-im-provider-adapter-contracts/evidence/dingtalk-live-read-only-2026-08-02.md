# DingTalk Live Read-Only Real-Execution Receipt

- Latest recorded at: `2026-08-02T18:44:45Z`
- Environment: authorized non-production app `hitl-im-dev`
- Adapter: production `DingTalkAdapter` API roles
- Fixture: `openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/dingtalk-live-read-only-2026-08-02.json`
- Data handling: credentials, corporation IDs, tenant IDs, user IDs, names, email addresses, access tokens, and raw Provider payloads are omitted
- Side effects: only credential and Directory operations ran; no message operation ran

## Executed operations

| Operation | Result |
| --- | --- |
| `credential.test_credentials` | Success. The production adapter identified the configured tenant and confirmed `contact.department.read` and `contact.user.read`. |
| `directory.read_snapshot` | Success. The immutable complete snapshot contained 2 entries. No identity values were emitted or retained. |

The credential and Directory run attached in-memory HTTP hooks before any public operation. It captured the CorpID-bound OAuth exchange, both permission probes, and the complete Directory traversal. The resulting snapshot contained 2 unique available entries; both exposed an Email. No identity value was emitted or retained.

## Unclosed evidence

- No Basic Messaging destination was available, so `basic_messaging.test_destination` and `basic_messaging.send_text` were not executed.

## Fixture status

The fixture retains the complete observed native request/response structures for `credential.test_credentials` and `directory.read_snapshot`. The CorpID OAuth path segment, credentials, tokens, request IDs, numeric department identities, user identities, names, emails, phone fields, and other PII are replaced with typed redaction markers.

Messaging fixtures remain `MISSING`. DingTalk Webhook and STREAM are outside this adapter scope and do not appear in the evidence inventory.
