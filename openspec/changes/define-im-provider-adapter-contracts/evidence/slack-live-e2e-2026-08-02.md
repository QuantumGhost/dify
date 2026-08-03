# Slack Live E2E Real-Execution Receipt

> Evidence boundary: messaging, card, and `block_actions` captures in this receipt are obsolete historical channel evidence.
> They predate the personal-user-only destination contract and do not close any current Slack Messaging, Dynamic Card,
> or interactive event evidence row. Credential, Directory, and independent endpoint-discovery observations remain
> eligible because they do not depend on the obsolete channel destination.

- Latest recorded at: `2026-08-02T20:47:05.572062Z`
- Environment: authorized non-production `Slack Test` workspace, `new-channel`
- Adapter: production `SlackAdapter` with the pinned Socket Mode SDK
- API fixture: `openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/slack-live-api-2026-08-02.json`
- STREAM fixture: `openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/slack-live-stream-2026-08-02.json`
- Endpoint-discovery fixture: `openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/slack-live-stream-2026-08-03.json`
- Socket `block_actions` fixture: `openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/slack-live-socket-block-actions-2026-08-03.json`
- Data handling: credentials, tenant/user/channel/message/envelope/request identities, PII, raw headers, and raw callback material are omitted

## Stateless and messaging batch

| Operation | Result |
| --- | --- |
| `credential.test_credentials` | Success. The credential-bound workspace was identified and `chat:write`, `users:read`, and `users:read.email` were confirmed. |
| `directory.read_snapshot` | Success. The immutable snapshot contained 5 entries with 5 unique Provider user IDs; 4 were available, 1 unavailable, and 2 exposed an Email. |
| `basic_messaging.test_destination` | Historical channel lookup failure; not evidence for the current `users.info` personal-user destination check. |
| `basic_messaging.send_text` | Historical channel-targeted send; not evidence for a direct personal-user send. |
| `dynamic_card.assess` | Pure local success. The one-submit-action intent was representable. |
| `dynamic_card.send_card` | Historical channel-targeted card send; not evidence for a personal-user card send. |

The fixture preserves the complete observed native request/response field and array shapes for these operations. All secrets and identities are replaced with typed redaction markers; the harmless English test content is retained intentionally.

## Fresh endpoint discovery and clean shutdown

One production `SlackAdapter` run using the pinned `slack-sdk==3.43.0` issued exactly one
`POST /api/apps.connections.open`. The in-process hook recursively sanitized the raw request and response before
the retained structure left memory. The response confirmed success and supplied connection material only to the
SDK; the fixture replaces that WSS URL and every header value with typed redaction markers.

The official Socket Mode client completed its real WSS handshake, then the harness raised the adapter stop signal
immediately. The stream run returned success, adapter close reported no error, the sink received zero events, and
no SDK runner remained alive. Automatic retries, message sends, GUI actions, and remote configuration writes were
all zero.

## Successful one-shot Socket Mode chain

At `2026-08-02T20:47:05.572062Z`, one production `SlackAdapter` run completed the full authorized non-production
chain without retry or Slack configuration changes: fresh endpoint discovery, real WSS connection, one Block Kit
card send, one GUI click, one authenticated `block_actions` delivery, one sink acceptance, one successful ACK, and
one exact-reference update.

| Counter or observation | Result |
| --- | ---: |
| Endpoint-discovery attempts / successes | 1 / 1 |
| WebSocket connection successes | 1 |
| `chat.postMessage` attempts | 1 |
| Rendered matching message containers / enabled buttons | 1 / 1 |
| GUI clicks | 1 |
| `block_actions` deliveries | 1 |
| Sink acceptances | 1 |
| Actual SDK delegate ACK attempts / successes | 1 / 1 |
| `chat.update` attempts | 1 |
| Same-container updates / matching updated titles / matching updated bodies | 1 / 1 / 1 |
| Remaining `Acknowledge` buttons / confirmed removals | 0 / 1 |
| Automatic retries | 0 |
| Residual runner threads | 0 |
| Duration | 137.513 seconds |

ACK instrumentation observed the pinned SDK's actual `send_socket_mode_response` delegate boundary, rather than
only recording adapter intent. The sink accepted the authenticated event before the delegate ACK succeeded, and
the run stopped only after that success, preserving ACK ownership inside the receiving callback path.

The callback container supplied the exact Slack channel and message timestamp used to construct an in-memory
`SlackMessageReference`. The same process passed that typed reference to `dynamic_card.update_card`; it was never
persisted or reconstructed from sanitized data. Across the retained fixture, five channel boundary values and eight
message-timestamp boundary values each collapse to exactly one category-specific run-local HMAC pseudonym, while
the channel and timestamp pseudonyms remain distinct. This correlates the send response, raw callback, normalized
event, update request, and update response without retaining the original references.

Slack accepted the single `chat.update` call. Structured GUI verification found one rendered message container and
one enabled `Acknowledge` button before the click, then proved that the same stable container exposed exactly one
updated title and body, no remaining button, and one confirmed removal.

The retained fixture was recursively sanitized before persistence and has SHA-256
`4172f1b7179fe506ce7c8de34a55a5abb0c69753f103ed4ec00b04fe31c41b20`. It preserves complete safe request,
response, delivery, normalized-event, ACK, and audit shapes while omitting credentials, identities, PII, raw
headers, URLs, WSS material, and raw message timestamps.

The fixture therefore supplies auditable sanitized evidence for both the Socket Mode delivery/ACK and the exact
reference update. The prior coarse-marker fixture was replaced atomically; no pseudonym was reconstructed from its
many-to-one markers.

## Earlier blocked Socket Mode attempt

The runner reached the post-`connect()` ready state before the card send. Read-only instrumentation was then attached to the official SDK request listener and ACK method.

| Counter or observation | Result |
| --- | ---: |
| Fresh card sends | 1 |
| Matching GUI card titles | 1 |
| Matching GUI card bodies | 1 |
| Enabled `Acknowledge` buttons before click | 1 |
| GUI clicks | 1 |
| Bounded receive window | 180 seconds |
| Raw Socket Mode requests observed | 0 |
| Normalized events delivered to the sink | 0 |
| ACKs sent | 0 |
| Exact-reference matches | 0 |
| Update attempts | 0 |
| Events API user messages sent | 0 |

The runner and adapter closed cleanly, the runner thread was no longer alive, and a later process audit found no remaining Socket Mode harness process. Because no authenticated callback arrived, this attempt is a blocker and supplies no interactive or ACK fixture. The card was not resent or clicked again, and no update was guessed.

Read-only UI inspection after the attempt found the fresh `Acknowledge` button still present. It found no visible `not configured`, generic failure, or interactivity message. No authenticated Slack developer configuration or delivery-log view was available in the bound tab, so no settings were inspected or changed.

## Read-only identity correlation

A separate single diagnostic connection registered a raw SDK message listener before `connect()`, inspected only the first `hello`, and then compared its app binding in memory with the app binding returned by read-only `auth.test` followed by `bots.info` using the same bot token. The connection closed immediately afterward.

```text
hello_seen=true
same_app=true
connection_count=one
```

No raw frame, Provider identity, token, connection URL, header, or payload was emitted or retained. This rules out an app-token versus bot-token app mismatch and multi-connection distribution for that diagnostic connection; it does not establish why the earlier click produced no callback.

## Historical Events API attempt (out of scope)

One production Socket Mode runner registered a raw SDK listener before `connect()`. It captured the first authentic `hello` frame, recursively sanitized the complete observed structure in memory, and confirmed `num_connections=1`. Only after that safety gate, the existing `new-channel` GUI composer sent exactly one harmless English user message:

```text
Dify IM adapter evidence check: Slack Events API user message accepted.
```

| Counter or observation | Result |
| --- | ---: |
| Authentic `hello` frames retained | 1 sanitized structure |
| Reported connections | 1 |
| GUI user-message sends | 1 |
| Automatic retries | 0 |
| Raw Events API requests observed | 0 |
| Normalized events delivered to the sink | 0 |
| Sink acceptances | 0 |
| Matching ACKs sent | 0 |

The bounded receive window ended without an Events API callback. The runner returned success, closed without error, and was no longer alive after stop. This historical, out-of-scope attempt supplies no evidence for the current `block_actions` cells, `stream.events_api.event_callback`, or ACK mapping. Its retained `stream.control.hello` observation remains historical context only. The message was not resent, no card operation was performed, and no remote configuration was inspected or changed.

## Earlier successful card chain

The earlier continuation run remains valid real-execution evidence only:

| Operation | UTC evidence time | Result |
| --- | --- | --- |
| `dynamic_card.send_card` | `2026-08-02T05:14Z` | Slack accepted one initial `Dify IM Adapter E2E` card. |
| `stream.interactive.block_actions` | `2026-08-02T05:47Z` | The production Socket Mode receiver accepted one authenticated `block_actions` callback; the sink ran once and the SDK sent one ACK after acceptance. |
| `dynamic_card.update_card` | `2026-08-02T05:47Z` | The exact reference came from the authenticated callback container. Slack accepted the update and the UI showed the same card as completed. |

The complete native callback and send/update payloads from that earlier process were not retained. It therefore does not fill any sanitized-fixture cell.

## Slash command inspection

The channel composer was given a single `/` draft for read-only affordance inspection, then cleared without submission. Slack displayed suggestions, but no explicit Dify command affordance was present. No command name was guessed and no slash command was sent. Real-execution and sanitized-fixture evidence for slash commands remains blocked.

## Evidence status

- Complete sanitized fixtures remain applicable to `credential.test_credentials` and `directory.read_snapshot`.
- Historical channel captures for `basic_messaging.test_destination`, `basic_messaging.send_text`, `dynamic_card.send_card`, `dynamic_card.update_card`, and `stream.interactive.block_actions` are obsolete and leave current personal-user rows `MISSING`.
- Complete sanitized real-execution evidence exists for `stream.control.hello`.
- `webhook.interactive.block_actions`, `stream.events_api.event_callback`, and `stream.slash_commands` still have no retained authentic sanitized fixture.
- The historical destination failure is not promoted to a current personal-user capability result.
