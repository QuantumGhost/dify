## ADDED Requirements

### Requirement: Member contacts can inherit a Feishu identity from their bound Dify account
The system SHALL allow a workspace member contact to use a Feishu IM identity that is bound through the corresponding Dify account.

#### Scenario: Logged-in account starts Feishu binding
- **WHEN** an authenticated Dify account starts the Feishu binding flow and the deployment has valid Feishu app credentials
- **THEN** the system starts a Dify-managed Feishu OAuth flow that can later bind the resulting Feishu identity back to that Dify account

#### Scenario: Successful callback stores the account binding
- **WHEN** the Feishu OAuth callback succeeds for a Dify account
- **THEN** the system stores or refreshes the Feishu provider binding for that account so the corresponding member contact can use it as IM identity

#### Scenario: Invalid callback state is rejected
- **WHEN** the Feishu OAuth callback arrives with missing, invalid, or unverifiable state
- **THEN** the system MUST NOT create or modify any Feishu binding

### Requirement: Demo-scope member contacts are bindable without Contact UI
The system SHALL support the Demo binding flow without requiring a Contact management UI.

#### Scenario: Imported member contact becomes bindable after account binding
- **WHEN** a workspace member has been imported into the Demo-scope Human Roster as a member contact and the corresponding Dify account completes Feishu binding
- **THEN** the imported member contact is treated as having an active Feishu IM identity

#### Scenario: Rebinding replaces the prior Feishu identity
- **WHEN** a Dify account with an existing Feishu IM binding completes a new successful binding flow
- **THEN** the system updates the prior binding instead of creating a second active binding for the same provider
