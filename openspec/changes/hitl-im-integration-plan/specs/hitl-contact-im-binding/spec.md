## ADDED Requirements

### Requirement: Member Contact can bind IM identity
系统 SHALL 允许 member Contact 对应的 Dify Account 绑定受支持 IM provider 的用户身份。

#### Scenario: Binding session is created
- **WHEN** 一个 authenticated Account 为受支持 provider 开始 IM binding
- **THEN** 系统 SHALL 创建带过期时间的 binding session，并绑定 account、provider、install mode、credential scope、provider workspace 和 provider user identity

#### Scenario: External Contact attempts binding
- **WHEN** external Contact 尝试绑定 IM identity
- **THEN** 系统 SHALL 拒绝绑定，因为 external IM identity 不在短期范围内

### Requirement: IM identity is verified before binding
系统 SHALL 只在 provider identity 经签名 callback、OAuth callback 或等价 provider-authenticated event 验证后保存 active binding。

#### Scenario: Verified identity completes binding
- **WHEN** Dify 收到有效 provider-authenticated binding callback
- **THEN** 系统 SHALL 将 Account 与 provider user identity 绑定

#### Scenario: Invalid provider callback is rejected
- **WHEN** Dify 收到 signature、timestamp 或 state 无效的 binding callback
- **THEN** 系统 SHALL 拒绝 callback，并 SHALL NOT 创建或更新 active binding

### Requirement: First phase allows one active IM provider per member
系统 SHALL 在 service 层限制第一期每个 member Contact/Account 只有一种 active IM，同时 DB SHALL 允许未来多 provider binding。

#### Scenario: Account already has active IM binding
- **WHEN** Account 已有一种 active IM binding 且尝试绑定另一种 provider
- **THEN** 系统 SHALL 在第一期拒绝第二种 active binding

#### Scenario: Future multiple provider bindings exist
- **WHEN** 后续版本允许多 provider binding
- **THEN** 现有 DB schema SHALL 能保存多条 provider binding，而无需数据迁移

### Requirement: Binding can be inspected and revoked
系统 SHALL 暴露当前 Account 的 active IM binding 状态，并允许撤销。

#### Scenario: Account views active binding
- **WHEN** bound Account 查看 IM binding 设置
- **THEN** 系统 SHALL 返回 provider、install mode、scope type、scope id、provider workspace、provider user display metadata 和 binding status

#### Scenario: Binding is revoked
- **WHEN** authorized user 撤销 active IM binding
- **THEN** 系统 SHALL 标记 binding inactive，并 SHALL NOT 将后续 HITL IM delivery 路由到该 binding

### Requirement: Binding stores credential scope without requiring installation foreign key
系统 SHALL 允许 IM binding 通过 credential scope 关联到 IM app config，而不是强制引用统一 installation 表。

#### Scenario: Deployment global self-built binding is stored
- **WHEN** Account 在 deployment global self-built app 下完成 IM binding
- **THEN** binding SHALL 保存 provider、install mode、scope type、scope id、provider workspace id 和 provider user id

#### Scenario: Future install table is introduced
- **WHEN** 后续版本为某些 provider 引入 install/config DB row
- **THEN** 现有 binding SHALL 能通过 credential scope 映射到该 config，而不要求重写 HITL 授权链路
