## ADDED Requirements

### Requirement: Messaging MUST be exposed as adapter-bound capabilities
Every initial `IMProviderAdapter` MUST expose Basic Messaging backed by the adapter-owned client context. Slack, Feishu/Lark and Microsoft Teams MUST additionally expose Dynamic Card Messaging. Messaging operations MUST NOT accept credentials, SDK clients or a generic integration context, and obtaining either capability MUST NOT construct an independent Provider client.

#### Scenario: Multiple Messaging operations use one adapter
- **WHEN** a caller tests a destination and then sends a message through the same adapter
- **THEN** both operations MUST reuse the adapter-owned client context without receiving credentials again

#### Scenario: Provider has no dynamic-card support
- **WHEN** a caller inspects Dynamic Card Messaging on DingTalk or WeCom
- **THEN** the capability MUST be absent and MUST NOT be represented by dummy unsupported methods

### Requirement: New-message operations MUST receive one explicit personal-user destination
A Provider message destination MUST address exactly one IM user and contain only the Provider-specific facts required to attempt that personal message. Group、channel、chat、department、tag 和其他 broadcast destinations MUST NOT exist in the public Messaging API. The destination MUST remain distinct from a Webhook endpoint and prior message reference. Messaging MUST use the supplied destination without invoking Directory. An authorized non-production test enterprise MUST allow any Directory user to be selected as a personal-message test candidate, while composition remains responsible for supplying any additional Provider-owned personal conversation context.

#### Scenario: Provider requires personal conversation context
- **WHEN** a Provider requires addressing facts beyond provider user ID for one personal message
- **THEN** Messaging MUST require those facts in the concrete personal destination and MUST NOT search Directory during send

#### Scenario: Caller attempts broadcast addressing
- **WHEN** a caller needs to address a group、channel、chat、department、tag or multiple users
- **THEN** this Messaging API MUST expose no destination type or branch for that operation

### Requirement: Basic Messaging MUST be implemented by every initial Provider
Slack, Feishu/Lark, DingTalk, WeCom and Microsoft Teams MUST implement Basic Messaging containing `test_destination` and `send_text` for exactly one personal user. Destination reachability MUST remain independent from adapter credential testing.

#### Scenario: Credentials are valid but one destination is unreachable
- **WHEN** adapter credential testing succeeds but one Provider message destination cannot receive a message
- **THEN** `test_destination` MUST return a destination-specific failure without changing credential-test facts

### Requirement: Dynamic Card Messaging MUST group assessment, send and update
Dynamic Card Messaging MUST contain side-effect-free card representability assessment, `send_card` and exact-reference card update. Assessment MUST receive only a normalized generic card intent and MUST return a boolean representability decision plus an optional human-readable reason. The reason MUST be used only for diagnostics and MUST NOT be parsed as a stable decision code.

The normalized card intent MUST preserve required text inputs, required single-select inputs with immutable labeled options, and an ordered set of actions. Text and single-select inputs MUST have unique stable input IDs. Actions MUST have unique stable action IDs and MAY contain multiple `SUBMIT` buttons. When inputs are present, at least one `SUBMIT` action MUST be present so the card remains completable. Slack, Feishu/Lark and Microsoft Teams MUST render these controls using their Provider-native form components rather than dropping inputs or replacing them with static text.

#### Scenario: Provider can represent a card intent
- **WHEN** assessment receives a normalized card intent that preserves its controls and semantics on the Provider
- **THEN** it MUST return true without sending a message or creating Provider state

#### Scenario: Provider cannot represent a card intent
- **WHEN** assessment receives a normalized card intent containing an unsupported control
- **THEN** it MUST return false with an optional reason and MUST NOT issue a Provider operation

#### Scenario: Card contains text, single-select and multiple submit controls
- **WHEN** assessment receives one required text input, one required single-select input and two or more submit actions
- **THEN** Slack, Feishu/Lark and Microsoft Teams MUST report the card as representable and MUST preserve every control in send and exact-reference update payloads

### Requirement: Basic and Dynamic Card Messaging MUST expose distinct send operations
Basic Messaging MUST expose `send_text`; Dynamic Card Messaging MUST expose `send_card`. `send_text` MUST receive one personal-user destination and one fully rendered CommonMark body without custom tags. The concrete adapter MUST render supported formatting for its Provider and MUST fall back to the same content as plain text when formatting is not expressible. `send_card` MUST receive one personal-user destination, one normalized card intent and one required immutable `OpaqueMetadata` value. Exact-reference card update MUST receive the same card intent and metadata inputs for the replacement rendering. `OpaqueMetadata` MUST contain string key/value pairs with unique, nonblank keys; construction MUST reject duplicate and blank or whitespace-only keys rather than silently collapsing or normalizing them. A nonblank key MUST retain its original string unchanged, and an opaque metadata value MAY be empty.

#### Scenario: Provider cannot express CommonMark formatting
- **WHEN** `send_text` receives valid CommonMark whose formatting cannot be represented on the target Provider
- **THEN** the concrete adapter MUST send equivalent plain text instead of rejecting the operation

#### Scenario: Card renderer rejects its input
- **WHEN** `send_card` receives an intent the concrete renderer cannot render
- **THEN** it MUST return a typed rendering failure before issuing any Provider send call and MUST NOT invoke `send_text` implicitly

#### Scenario: Caller metadata contains duplicate keys
- **WHEN** a caller constructs `OpaqueMetadata` with the same key more than once
- **THEN** construction MUST fail before any card renderer or Provider operation can observe an ambiguous mapping

#### Scenario: Caller metadata contains a blank key
- **WHEN** a caller constructs `OpaqueMetadata` with an empty or whitespace-only key
- **THEN** construction MUST fail without changing the spelling or whitespace of any valid nonblank key

### Requirement: Caller metadata MUST round-trip only through submit controls
Caller metadata MUST remain an opaque correlation hint. The concrete adapter MUST embed the complete metadata as one nested object inside every `SUBMIT` action produced by that `send_card` or update invocation, while preserving the action's `action_id` and `value`. It MUST NOT attach metadata to `OPEN_URL` actions. Feishu/Lark and Microsoft Teams MUST use Provider-native nested submit objects. Slack MUST use a versioned compact JSON button value containing the action value and nested metadata.

Provider-native text and single-select values MUST be returned alongside the selected submit action in the authenticated callback payload. They MUST remain Provider-native payload fields; the Provider adapter MUST NOT combine them with opaque metadata or decode them into a consumer form model.

Metadata returned through a Provider interaction MUST be treated as untrusted end-user-controlled input and MUST NOT be used as authentication or authorization evidence. The Provider adapter MUST retain the authenticated Provider-native callback payload without converting it into a shared business submission. An independent consumer or decoder MUST interpret the Provider-specific submit envelope and authorize the action from trusted application state. Metadata MUST NOT replace the exact Provider message reference used for card updates, and this contract MUST NOT introduce a separate shared card correlation token.

#### Scenario: Card contains submit and open-URL actions
- **WHEN** a concrete adapter renders a card with both action kinds
- **THEN** each submit action MUST contain its original action ID and value plus nested caller metadata, while the open-URL action MUST contain no caller metadata

#### Scenario: Consumer receives returned metadata
- **WHEN** an authenticated Provider callback contains metadata previously emitted in a submit control
- **THEN** the adapter MUST preserve it only as part of the Provider-native payload and the consumer MUST NOT authorize the action from that metadata

#### Scenario: Consumer receives submitted form controls
- **WHEN** a user enters text, chooses one option and activates one of multiple submit actions
- **THEN** the authenticated Provider-native payload MUST preserve the entered text, selected option, selected action ID/value and complete opaque metadata without treating any of them as authorization evidence

#### Scenario: Slack submit envelope exceeds the Provider limit
- **WHEN** one complete Slack versioned submit value exceeds 2000 bytes when encoded as UTF-8
- **THEN** Slack Dynamic Card Messaging MUST return a typed rendering failure before any Provider call

### Requirement: Successful send MUST return Provider acceptance and an exact message reference
A successful personal `send_text` or `send_card` MUST return available Provider acceptance facts and a Provider-discriminated message reference sufficient to target that exact message later. Provider acceptance MUST remain distinct from end-user delivery, and the shared contract MUST NOT assume one scalar message ID format.

#### Scenario: Providers return different message locators
- **WHEN** Slack identifies a message by channel and timestamp while Feishu/Lark identifies it by message ID
- **THEN** Messaging MUST preserve each Provider's exact reference without coercing both into one global identifier

### Requirement: One side-effecting Messaging invocation MUST call the Provider at most once
`test_destination`, `send_text` and `send_card` MUST NOT automatically replay a side-effecting Provider call after timeout, connection reset, rate limit or ambiguous failure. One method invocation MUST issue at most one such call and MUST return a typed known or ambiguous outcome.

#### Scenario: Send result is ambiguous
- **WHEN** the adapter cannot determine whether a timed-out Provider request created a message
- **THEN** it MUST return an ambiguous outcome and MUST NOT call the Provider again

### Requirement: Dynamic Card Messaging MUST update the exact prior message reference
Card update MUST target only the Provider message reference returned by the corresponding `send_card` result. The shared contract MUST preserve Slack channel and timestamp, Feishu/Lark message ID, and Microsoft Teams activity and conversation context as Provider-discriminated locators. Update MUST return its own typed outcome without changing the earlier send result.

#### Scenario: Prior message reference is stale
- **WHEN** the Provider no longer accepts the stored message reference
- **THEN** card update MUST return a typed stale-reference failure and MUST NOT infer another message instance
