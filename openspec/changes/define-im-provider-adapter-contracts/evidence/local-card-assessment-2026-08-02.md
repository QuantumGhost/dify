# Local Dynamic-Card Assessment Real-Execution Receipt

- Recorded at: `2026-08-02T10:21:53Z`
- Environment: authorized non-production configurations loaded from `temp/im.env`
- Adapters: production `SlackAdapter`, `FeishuLarkAdapter`, and `MicrosoftTeamsAdapter`
- Data handling: credentials and Provider identifiers remained in process memory and were neither emitted nor retained
- Side effects: assessment is a local representability decision; no Provider HTTP, stream, message, Webhook, or event operation ran

## Executed operations

| Provider | Operation | Result |
| --- | --- | --- |
| Slack | `dynamic_card.assess` | `CardAssessment(representable=True, reason=None)` |
| Feishu/Lark | `dynamic_card.assess` | `CardAssessment(representable=True, reason=None)` |
| Microsoft Teams | `dynamic_card.assess` | `CardAssessment(representable=True, reason=None)` |

## Lifecycle evidence

- Each assessment used the public dynamic-card capability exposed by its production adapter.
- Each adapter initialized and closed its owned local client context without starting a stream or issuing a Provider request.
- The assessed generic intent contained a title, body, one fact, fallback text, and no actions.

## Fixture status

Assessment consumes only the normalized generic intent and produces no external Provider request, response, or event payload. Its `sanitized_fixture` evidence is therefore `N/A`; no fixture was created.
