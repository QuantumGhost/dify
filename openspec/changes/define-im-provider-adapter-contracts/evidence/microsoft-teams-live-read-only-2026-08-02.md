# Microsoft Teams Live Read-Only Real-Execution Receipt

- Recorded at: `2026-08-02T13:01:08Z`
- Environment: authorized non-production Microsoft Graph configuration loaded from gitignored `temp/im.env`
- Adapter: production `MicrosoftTeamsAdapter`
- Fixture: `openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/microsoft-teams-live-read-only-2026-08-02.json`
- Data handling: credentials, tenant/client/user identities, names, email addresses, tokens, JWT claims, dynamic path segments, and raw headers are omitted
- Side effects: only OAuth and Microsoft Graph reads ran; no Bot Framework token, conversation, message, card, Webhook, app installation, endpoint, permission, or configuration operation ran

## Executed operations

| Operation | Result |
| --- | --- |
| `credential.test_credentials` | Typed `missing_permission` failure. The issued Graph token did not contain `Organization.Read.All`, so the adapter stopped before the organization request. |
| `directory.read_snapshot` | Success under the independently present `User.Read.All` role. The immutable snapshot contained 3 entries with 3 unique Provider user IDs; all 3 exposed an Email and availability was unknown. |

The credential result is authentic failure evidence, not a successful credential test. Directory success is separately valid because the adapter's cached token had the role required for `/v1.0/users`.

## Composition boundary

No independent bot-app environment role was available or needed for these Graph-only paths. The ephemeral config reused the existing client identifier solely to satisfy the unused constructor field and recorded `bot_app_id_material_used=false`. The trusted service-origin allowlist was empty, so no Bot Framework operation could run.

## Sanitized fixture

The fixture retains the complete observed native structures for:

- `POST /<redacted:path-segment>/oauth2/v2.0/token`
- `GET /v1.0/users`

The tenant path, form values, access token, Graph identities, display names, and email addresses are replaced with typed redaction markers.

## Blockers

- Credential success requires `Organization.Read.All`; no permission was requested or granted.
- No exact authenticated conversation, service URL, trusted origin, or Bot Framework installation was available. Destination testing, messaging, card send/update, and Webhook execution were not attempted.
