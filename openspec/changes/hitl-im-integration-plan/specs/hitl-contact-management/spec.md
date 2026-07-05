## ADDED Requirements

### Requirement: Workspace scoped Contact is managed
系统 SHALL 支持 Workspace-scoped Contact，其中 member Contact 引用 Dify Account，external Contact 只保存 name 和单个 email。`Contact` SHALL 作为 authoritative workspace recipient row 持久化，而不是在运行时按 membership 临时投影。member Contact 的 profile 读路径 SHALL 以 `Account` 为准，而 `Contact.name/email` SHALL 只作为 bootstrap/fallback cache；external Contact 的 profile 读路径 SHALL 以 `Contact` 自身为准。

#### Scenario: Demo seed creates member Contacts
- **WHEN** demo 或测试环境需要准备 Contact 数据
- **THEN** 系统 SHALL 提供脚本从现有 Workspace members 创建对应 member Contacts

#### Scenario: External Contact is manually created
- **WHEN** 用户在 Workspace 内手动创建 external Contact
- **THEN** 系统 SHALL 保存该 Contact 的 name 和 email，并 SHALL NOT 要求绑定 Account 或 IM identity

### Requirement: Contact demo seeding avoids full historical migration
系统 SHALL 避免把现有 `TenantAccountJoin` 全量拷贝到 Contact 表作为一次性迁移。demo 阶段 SHALL 只提供显式 seed script 用于从现有 Workspace members 创建 Contact。

#### Scenario: Seed script runs for workspace
- **WHEN** operator 对指定 Workspace 运行 Contact seed script
- **THEN** 系统 SHALL 为该 Workspace 中已有 members 创建缺失的 member Contacts，并 SHALL 保持已有 Contacts 不被重复创建

#### Scenario: Seed script does not act as sync
- **WHEN** operator 再次运行 Contact seed script
- **THEN** 系统 SHALL 只补齐缺失 Contact，并 SHALL NOT 把该脚本视为 profile sync、automatic reactivation 或 runtime lazy materialization

#### Scenario: Automatic sync is out of demo scope
- **WHEN** 用户加入或离开 Workspace
- **THEN** demo 实现 SHALL NOT 依赖自动 Contact 同步或 lazy materialization；正式同步策略 SHALL 后续单独设计

### Requirement: HITL keeps Contact snapshot
系统 SHALL 在 HITL runtime 记录 Contact snapshot，避免 Contact 后续变化破坏历史审计。

#### Scenario: Form recipient is created
- **WHEN** HITL runtime 为 Contact recipient 创建 form recipient
- **THEN** 系统 SHALL 保存 contact id、type、account id、name、email、source 和当时的 channel/binding 信息

#### Scenario: Contact is later removed
- **WHEN** 历史 HITL 表单引用的 Contact 后续被删除或失效
- **THEN** 系统 SHALL 继续通过 snapshot 展示当时的接收人和提交人信息

### Requirement: Contact uniqueness is enforced per workspace
系统 SHALL 保证同一个 Workspace 内一个 Account 对应唯一 authoritative member Contact row，active/disabled 状态在该 row 上流转。

#### Scenario: Duplicate member Contact is created
- **WHEN** 系统尝试为同一 Workspace 和 Account 创建第二个 active member Contact
- **THEN** 系统 SHALL 返回已有 Contact 或拒绝重复创建

#### Scenario: Disabled member Contact still owns the member identity
- **WHEN** 同一 Workspace 内某个 member Contact 已存在但状态为 disabled
- **THEN** 系统 SHALL 继续把该 row 视为该 member 的 authoritative Contact identity，而 SHALL NOT 通过 seed script 创建第二条 member Contact row
