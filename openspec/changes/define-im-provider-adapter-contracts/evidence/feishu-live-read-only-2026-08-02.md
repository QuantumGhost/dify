# Feishu Live Read-Only Real-Execution Receipt

- Latest recorded at: `2026-08-02T18:03:21Z`
- Environment: authorized non-production configuration loaded from gitignored `temp/im.env`
- Adapter: production `FeishuLarkAdapter` configured for Feishu
- Fixture: `openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/feishu-live-read-only-2026-08-02.json`
- STREAM endpoint-discovery fixture: `openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/feishu-live-stream-2026-08-03.json`
- Data handling: credentials, tenant/app/user identities, names, contact data, tokens, dynamic path segments, raw headers, connection URLs, and raw stream frames are omitted
- Side effects: credential and directory reads plus one bounded official SDK connection lifecycle; no message, card, Webhook, configuration, subscription, or permission operation ran

## Executed operations

| Operation | Result |
| --- | --- |
| `credential.test_credentials` | Success. The production adapter identified the configured tenant and confirmed `tenant:tenant:readonly` plus `contact.scope.read`. |
| `directory.read_snapshot` | Typed `missing_permission` failure: `contact:user.base:readonly` is absent. The Provider returned one scoped user object without the base field required to construct a valid directory entry. No partial snapshot escaped. |
| `stream.stop` | One official controlled SDK connection opened, then stopped immediately through the public stop signal. The run returned normally, delivered zero sink events, left no runner thread alive, and closed without error. |
| `stream.connect` | The production adapter and pinned `lark-oapi==1.7.1` issued exactly one `POST /callback/ws/endpoint`, completed the real WSS handshake, and stopped immediately. The discovery response was recursively sanitized in memory before retention. |

The Directory outcome is authentic failure evidence, not a successful snapshot.

## Sanitized fixture

The fixture retains the complete observed native structures for:

- `POST /open-apis/auth/v3/tenant_access_token/internal`
- `GET /open-apis/tenant/v2/tenant/query`
- `GET /open-apis/contact/v3/scopes`
- `GET /open-apis/contact/v3/users/<redacted:path-segment>`

Repeated identical calls are represented by explicit catalog references. All identities and PII are replaced with typed redaction markers. No stream frame was retained, so `stream.control` and `stream.event_callback` fixtures remain `MISSING`.

The separate STREAM endpoint-discovery fixture preserves the complete observed request/response field and array
shape, including header names with every value redacted. App credentials, Provider identities, request IDs, raw
header values, and the WSS URL are not retained. The run used no automatic retry, sent no message, delivered no
sink event, changed no remote configuration, and left no residual runner after adapter close.

## Blockers

- Complete Directory success requires the existing app to receive `contact:user.base:readonly`; no permission was requested or changed.
- No exact existing destination was available. Destination testing, text/card send, and exact-reference update were not attempted.
- No authenticated Webhook or business stream event was observed; those real and fixture cells remain `MISSING`.
