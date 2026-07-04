## ADDED Requirements

### Requirement: IM and initiator submissions use Human Input submission service
系统 SHALL 将有效 IM submission 和 initiator approval 都路由到现有 Human Input submission service，而不是从 callback 直接恢复 workflow。

#### Scenario: Valid IM submission is stored
- **WHEN** verified IM callback 匹配 active Human Input form recipient
- **THEN** 系统 SHALL 使用 recipient token、selected action、normalized form data 和 Account actor 调用 Human Input submission path

#### Scenario: Valid initiator approval is stored
- **WHEN** authorized current initiator 提交 HITL form
- **THEN** 系统 SHALL 使用 Account 或 EndUser actor 调用 Human Input submission path

#### Scenario: Callback attempts direct runtime resume
- **WHEN** 实现 provider callback handling
- **THEN** 实现 SHALL NOT 绕过 Human Input form validation、submitted status update 或 expiration checks

### Requirement: Workflow resumes after first valid submission
系统 SHALL 在 runtime form 第一次有效提交后继续暂停中的 HITL workflow。

#### Scenario: Runtime workflow form is submitted
- **WHEN** IM callback 或 initiator approval 成功提交带 `workflow_run_id` 的 runtime Human Input form
- **THEN** 系统 SHALL 对该 workflow run enqueue existing workflow resume task exactly once

#### Scenario: Agent conversation form is submitted
- **WHEN** IM callback 或 initiator approval 成功提交只有 `conversation_id` 的 runtime Human Input form
- **THEN** 系统 SHALL 对该 conversation enqueue existing Agent App resume task exactly once

### Requirement: Expired or inactive forms do not resume
系统 SHALL 拒绝 expired、timed out、inactive 或 already submitted form 的 submission。

#### Scenario: Expired form callback arrives
- **WHEN** IM callback 或 initiator approval 目标 form 已超过 expiration time 或 global timeout
- **THEN** 系统 SHALL 拒绝 submission，并 SHALL NOT enqueue workflow resume

#### Scenario: Already submitted form callback arrives
- **WHEN** IM callback 或 initiator approval 目标 form 已被另一有效 recipient 提交
- **THEN** 系统 SHALL 保留原始 submission，并 SHALL NOT 再次 enqueue workflow resume

### Requirement: Resume path is observable
系统 SHALL 记录连接 callback / initiator approval、form submission 和 workflow resume 的日志与状态。

#### Scenario: Submission resumes workflow
- **WHEN** submission 成功导致 workflow resume enqueue
- **THEN** 日志或持久化 metadata SHALL 包含 tenant id、app id、workflow run 或 conversation id、form id、contact snapshot、provider、provider message id 和 callback event id

#### Scenario: Resume enqueue fails
- **WHEN** form submission 成功但 resume enqueue 失败
- **THEN** 系统 SHALL 记录带 form 和 workflow identifiers 的错误，便于诊断
