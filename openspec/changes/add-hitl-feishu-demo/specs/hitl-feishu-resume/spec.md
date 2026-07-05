## ADDED Requirements

### Requirement: Feishu card actions are consumed through a long-connection listener
The system SHALL consume Feishu HITL interactions from a Dify-managed long-connection listener that runs independently from the normal web request worker lifecycle.

#### Scenario: Listener receives a card action for a Dify HITL form
- **WHEN** Feishu emits a card action for a HITL notification that was previously sent by Dify
- **THEN** the long-connection listener hands the action into Dify's HITL callback handling flow

### Requirement: Feishu submissions reuse the canonical HITL recipient-token path
The system SHALL resume workflows from Feishu interactions by resolving the intended member recipient and then submitting through Dify's existing recipient-token-based HITL submission path.

#### Scenario: Bound operator submits a supported interactive card
- **WHEN** the listener receives a Feishu card action whose operator is bound to the Dify account that matches a target member recipient for that form
- **THEN** the system submits the form through the canonical HITL recipient-token path and continues the existing workflow resume logic

#### Scenario: Identity mismatch is rejected
- **WHEN** the listener receives a Feishu interaction whose operator cannot be matched to the intended member recipient
- **THEN** the system rejects the submission and MUST NOT resume the workflow

### Requirement: Successful Feishu completion updates the IM-side result state
The system SHALL mark the IM-side notification as completed after the first successful submission.

#### Scenario: Card submission returns readonly result card
- **WHEN** a recipient successfully submits a supported interactive Feishu card
- **THEN** the callback response replaces the original interactive card with a readonly result card that reflects the submitted values and final action

#### Scenario: Link-based submission still closes the IM-side task state
- **WHEN** a recipient completes the HITL task through the fallback web approval link after arriving from Feishu
- **THEN** the system records the Feishu-side notification as completed so duplicate later actions are not accepted

### Requirement: Repeated or stale Feishu actions are idempotent
The system MUST prevent repeated or stale Feishu interactions from resubmitting an already completed or expired HITL task.

#### Scenario: Duplicate action arrives after submission
- **WHEN** the listener receives a later Feishu action for a form that has already been submitted
- **THEN** the system does not create a second submission or trigger a second workflow resume

#### Scenario: Action arrives after expiration
- **WHEN** the listener receives a Feishu interaction for a form that is expired or timed out
- **THEN** the system rejects the interaction and does not resume the workflow
