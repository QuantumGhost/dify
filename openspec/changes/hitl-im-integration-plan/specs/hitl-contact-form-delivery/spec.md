## ADDED Requirements

### Requirement: New HITL node uses Contact recipients
系统 SHALL 提供新的 HITL `NodeType` 和 `Version`，其 recipient 配置基于 Contact，而不是旧 delivery method。

#### Scenario: New HITL node is configured
- **WHEN** 用户配置新的 HITL node
- **THEN** 系统 SHALL 保存 Contact recipients 和 `allow_current_initiator_to_approve` 配置

#### Scenario: Demo uses existing frontend orchestration
- **WHEN** demo 阶段用户在现有前端 HumanInput v1 配置面完成编排
- **THEN** 系统 SHALL 接受前端提交的 v1 node config，而不要求新的 v2 Contact recipient 配置 UI

#### Scenario: Demo maps v1 config to v2 runtime
- **WHEN** demo 阶段 runtime 收到 HumanInput v1 node config
- **THEN** 系统 SHALL 在执行前将 v1 node config 映射为 HumanInput v2 runtime model，并 SHALL 使用 v2 runtime 执行

#### Scenario: Compatibility layer remains transitional
- **WHEN** 系统使用 v1 config 到 v2 runtime model 的映射
- **THEN** 系统 SHALL 将该路径视为 demo / migration transitional path，并 SHALL NOT 将 v1 config shape 作为正式 v2 schema 的长期契约

### Requirement: Member Contact delivery falls back to email
系统 SHALL 对 member Contact 优先使用 IM binding 投递；未绑定 IM 时 fallback 到 email；email 不可用时 skip。

#### Scenario: Bound member receives IM form
- **WHEN** HITL form 创建且 member Contact 有 active IM binding
- **THEN** 系统 SHALL 向对应 IM provider 发送 rendered form content、支持的 inputs、actions 和 expiration metadata

#### Scenario: Member has no IM binding
- **WHEN** HITL form 创建且 member Contact 没有 active IM binding
- **THEN** 系统 SHALL 使用 member email 发送通知，并 SHALL 在节点 `process_data` 记录 fallback 状态

#### Scenario: Member has no usable contact method
- **WHEN** HITL form 创建且 member Contact 没有 IM binding 也没有 email
- **THEN** 系统 SHALL skip 该 recipient，并 SHALL 在节点 `process_data` 记录 skip 状态

### Requirement: External Contact uses email only
系统 SHALL 对 external Contact 只使用 email 投递。

#### Scenario: External Contact receives form
- **WHEN** HITL form 创建且 recipient 是 external Contact
- **THEN** 系统 SHALL 使用该 Contact 的 email 发送通知，并 SHALL NOT 尝试 IM binding

### Requirement: IM form rendering supports HITL input types
系统 SHALL 支持 paragraph、select、file、file-list 和 actions；provider 原生不支持的输入 SHALL 使用 Web form fallback。

#### Scenario: Supported inline inputs are rendered
- **WHEN** HITL form 包含 paragraph、select 和 actions
- **THEN** 系统 SHALL 在 IM message/card 内渲染这些字段以允许 IM 内提交

#### Scenario: File inputs require fallback
- **WHEN** HITL form 包含 file 或 file-list 且 provider card 不支持安全上传
- **THEN** 系统 SHALL 在 IM message/card 中提供安全 Web form link

### Requirement: Current initiator can approve when enabled
系统 SHALL 在启用 `Allow Current Initiator to Approve` 时允许当前发起者通过对应 surface 提交表单。

#### Scenario: Console or CLI OpenAPI initiator approves
- **WHEN** Console 或 CLI OpenAPI 发起者提交 HITL form
- **THEN** 系统 SHALL 将提交 actor 解析为 Account

#### Scenario: Web App or Service API initiator approves
- **WHEN** Web App 或 Service API 发起者提交 HITL form
- **THEN** 系统 SHALL 将提交 actor 解析为 EndUser

### Requirement: Delivery correlation is persisted
系统 SHALL 持久化 provider 和 Dify correlation 数据，以便 callback、补偿和排障。

#### Scenario: Provider message is sent
- **WHEN** IM provider 接受 form message
- **THEN** 系统 SHALL 保存 form id、recipient snapshot、provider、provider workspace id、provider message id、delivery status、sent time 和 interaction mapping snapshot

#### Scenario: Provider send fails
- **WHEN** IM provider 发送失败或超时
- **THEN** 系统 SHALL 保存 failure status 和 error details，并 SHALL NOT 将 HITL form 标记为 submitted 或 failed

### Requirement: Interaction mapping snapshot is persisted
系统 SHALL 在发送 IM message/card 时保存 provider component/action id 到 Dify form 语义的 mapping snapshot。

#### Scenario: Inline inputs and actions are rendered
- **WHEN** 系统渲染可在 IM 内提交的 input 和 action
- **THEN** 系统 SHALL 保存每个 provider input component id 对应的 Dify `output_variable_name`，以及每个 provider action id 对应的 Dify `user_actions[].id`

#### Scenario: Form definition changes after message is sent
- **WHEN** IM message/card 发送后 HITL node config 或 form definition 发生变化
- **THEN** 后续 callback SHALL 仍使用发送时保存的 interaction mapping snapshot 解释该消息
