# WeCom Live API Real-Execution Receipt

- Latest recorded at: `2026-08-02T12:37:03Z`
- Environment: authorized tenant configuration loaded from gitignored `temp/im.env`
- Adapter: production `WeComAdapter`
- Fixture: `openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/wecom-live-api-2026-08-02.json`
- Data handling: credentials, corporation/agent/department/tag/user/message identities, names, contact data, access tokens, raw headers, and raw Provider payloads are omitted

## Executed operations

| Operation | Result |
| --- | --- |
| `credential.test_credentials` | Success. One token request and one agent-visibility request completed; `agent.visibility.read` was confirmed. |
| `directory.read_snapshot` | Success. The immutable snapshot contained 2 entries with 2 unique Provider user IDs. Both were available and neither exposed an Email. |
| `basic_messaging.test_destination` | Success. A single destination was selected only in memory from the directory snapshot and confirmed inside the bound agent visibility. |
| `basic_messaging.send_text` | Exactly one call. WeCom accepted the harmless English message and returned an exact message reference. No retry was attempted. |

## Binding and target handling

- Each of the three production configuration roles (`corp_id`, `agent_id`, and `corp_secret`) resolved to exactly one provider-scoped environment-variable suffix match. The separate destination-selection provenance boolean is not a configuration role.
- The credential result and directory snapshot were bound to the configured corporation; the identifier was never emitted or retained.
- The outbound target was one existing, available identity from the just-read directory snapshot. It existed only in process memory and was not emitted or retained.
- The destination check traversed the returned department visibility before success. No remote configuration operation ran.

## Sanitized fixture

The fixture preserves the complete observed native structures for:

- `GET /cgi-bin/gettoken`
- `GET /cgi-bin/agent/get`
- `GET /cgi-bin/department/list`
- `GET /cgi-bin/user/list`
- `POST /cgi-bin/message/send`

Repeated identical structures are represented through explicit catalog references with operation-local call IDs. Numeric agent and department identities are replaced with typed redaction markers as well as string identities and secrets. The harmless English message body is retained intentionally.

## Evidence status

- Credential testing has complete real-execution and sanitized-fixture evidence for its two exact API entries.
- Directory evidence covers the observed agent-visibility, department-list, and department-user entries. Unobserved explicit-user and tag-derived branches keep the aggregate Directory evidence `MISSING`.
- Destination-testing evidence covers the observed agent-visibility and department traversal entries. Its cold-token entry and unobserved visibility branches keep the aggregate destination evidence `MISSING`.
- Basic text messaging evidence covers the observed message-send entry. Its cold-token entry remains `MISSING`, so the aggregate send evidence also remains `MISSING`.
- This receipt makes no evidence claim beyond credential, Directory, and Basic Messaging API entries.
