## ADDED Requirements

### Requirement: Provider callbacks are verified
系统 SHALL 在解析或提交任何 IM 表单 payload 前验证 provider callback。

#### Scenario: Valid callback is accepted
- **WHEN** Dify 收到 signature、timestamp 和 app context 有效的 IM callback
- **THEN** 系统 SHALL 使用对应 provider adapter 解析 callback

#### Scenario: Invalid callback is rejected
- **WHEN** Dify 收到 signature、timestamp 或 app context 无效的 IM callback
- **THEN** 系统 SHALL 拒绝 callback，并 SHALL NOT 读取或提交嵌入的表单 payload

### Requirement: Callback maps to Dify form submission
系统 SHALL 将 provider-specific IM form submission 转换为 Dify Human Input submission data。

#### Scenario: IM user submits form fields
- **WHEN** bound IM user 从 IM message/card 提交字段和 action
- **THEN** 系统 SHALL 使用服务端保存的 interaction mapping snapshot 映射为 `selected_action_id` 和 `form_data`，并传给 `HumanInputService.submit_form_by_token`

#### Scenario: Provider payload is malformed
- **WHEN** provider callback 缺少 action、correlation 或 field data
- **THEN** 系统 SHALL 返回 provider-compatible error response，并 SHALL NOT 标记 Dify form submitted

#### Scenario: Callback contains unknown component
- **WHEN** provider callback 携带 interaction mapping snapshot 中不存在的 input component id 或 action id
- **THEN** 系统 SHALL 拒绝 submission，并 SHALL NOT 将未知字段透传到 Dify form data

#### Scenario: Provider payload includes Dify field names
- **WHEN** provider callback payload 直接携带 Dify `action_id` 或 `output_variable_name`
- **THEN** 系统 SHALL 只把这些字段视为不可信外部输入，并 SHALL 使用服务端 interaction mapping snapshot 做最终翻译

### Requirement: Callback user must match Contact recipient
系统 SHALL 只接受 provider user 与原始 Contact recipient snapshot / active binding 匹配的 IM submission。

#### Scenario: Matching bound user submits
- **WHEN** callback provider user 匹配 active binding 和原始 Contact recipient snapshot
- **THEN** 系统 SHALL 以对应 Account 提交 Dify form

#### Scenario: Different IM user submits
- **WHEN** callback provider user 不匹配原始 Contact recipient snapshot 或 active binding
- **THEN** 系统 SHALL 拒绝 submission，并 SHALL NOT 向该用户暴露 form data

### Requirement: Callback processing is idempotent
系统 SHALL 幂等处理重复 provider callback event，避免重复提交或重复 resume。

#### Scenario: Duplicate callback arrives
- **WHEN** Dify 多次收到同一 provider event id
- **THEN** 系统 SHALL 返回成功 ACK，并 SHALL NOT 再次提交 form 或 enqueue resume

#### Scenario: Different callback targets submitted form
- **WHEN** 不同 callback 尝试提交已经 submitted 的 form
- **THEN** 系统 SHALL 返回 already-handled response，并 SHALL NOT 覆盖原始 submitted data

### Requirement: Provider card state is updated with compensation
系统 SHALL 在 IM submission 后更新 provider card 状态，并在更新失败时异步补偿。

#### Scenario: Submission succeeds
- **WHEN** Dify 接受并存储 IM form submission
- **THEN** 系统 SHALL 尝试把 provider card 更新为 submitted 状态

#### Scenario: Card update fails
- **WHEN** provider card update 失败
- **THEN** 系统 SHALL 记录补偿任务，并 SHALL NOT 阻塞 workflow resume

#### Scenario: Submission fails validation
- **WHEN** Dify 因 validation 或 expiration 拒绝 IM submission
- **THEN** 系统 SHALL 尝试把 provider card 更新为 error 或 expired 状态
