## ADDED Requirements

### Requirement: Existing member recipients resolve to Demo-scope member contacts
The system SHALL interpret existing HITL `member` recipients as member contacts in the Demo-scope Human Roster compatibility layer.

#### Scenario: Workspace member can be imported as a contact
- **WHEN** an operator runs the Demo contact bootstrap for a workspace
- **THEN** the system materializes current workspace members as member contacts that can be resolved during HITL delivery

#### Scenario: HITL member recipient resolves to imported contact
- **WHEN** a HITL node contains a static `member` recipient that refers to a workspace member account
- **THEN** the delivery pipeline resolves that recipient to the corresponding imported member contact before choosing delivery channels

#### Scenario: Contact initialization is script-only in Demo scope
- **WHEN** the CE Demo environment needs member contacts for HITL delivery
- **THEN** the system initializes those contacts through an operator-run import script rather than through contact create or edit product flows

### Requirement: Bound member contacts receive IM and Email by default
The system SHALL follow the PRD default dual-channel rule for member contacts that have a usable Feishu IM identity.

#### Scenario: Bound member contact receives dual-channel notification
- **WHEN** a runtime HITL form targets a member contact with an active Feishu IM binding and an email address
- **THEN** the system sends a Feishu notification and preserves the existing email notification for that same recipient

#### Scenario: Unbound member contact falls back to email-only
- **WHEN** a runtime HITL form targets a member contact that has no active Feishu IM binding
- **THEN** the system leaves that recipient on the existing email path and does not fail the overall delivery

#### Scenario: External or dynamic email recipient remains email-only
- **WHEN** a runtime HITL form targets an external recipient, one-time email recipient, or dynamic email variable recipient
- **THEN** the system keeps that recipient on the existing email-only path

### Requirement: Feishu delivery is card-first with link fallback
The system SHALL prefer interactive Feishu cards for supported HITL forms and fall back to an approval link when the form cannot be represented safely in a card.

#### Scenario: Text and single-select form renders as interactive card
- **WHEN** a HITL form contains only paragraph inputs, select inputs, and supported actions
- **THEN** the system sends a Feishu interactive card for that member contact

#### Scenario: Unsupported form falls back to IM approval link
- **WHEN** a HITL form contains inputs that are outside the Demo Feishu card capability set
- **THEN** the system sends an IM notification with an approval link to the existing web HITL form instead of sending a partial or invalid card

### Requirement: Feishu sends are auditable
The system SHALL persist auditable records for Feishu delivery attempts and successful sends.

#### Scenario: Successful Feishu send stores message correlation data
- **WHEN** the system successfully sends a Feishu notification for a HITL recipient
- **THEN** it stores the correlation fields needed to trace delivery status and later process callback events

#### Scenario: Failed Feishu send stores failure status
- **WHEN** the Feishu send attempt fails
- **THEN** the system records the failure status and reason for that IM delivery attempt
