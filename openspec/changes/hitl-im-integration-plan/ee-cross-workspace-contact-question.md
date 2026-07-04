# EE 跨 Workspace Contact 待决策问题

## 背景

EE 部署中，同一个部署下的多个 Workspace 通常属于同一个实体。新的 HITL IM 设计允许某个 Workspace 的 Contact 包含其他 Workspace 的 Dify Account，即这个 Contact 对应真实 `Account`，但不一定存在当前 Workspace 的 `TenantAccountJoin`。

这与现有很多 Dify 权限/审计路径不同：当前代码通常通过 `TenantAccountJoin` 判断 Account 是否属于当前 Workspace，并通过 `current_tenant` / `current_role` 推导 workspace-scoped 权限。

## 已明确原则

- 新 HITL callback 授权应优先基于当前 Workspace 的 Contact recipient / Contact snapshot，而不是只基于 `TenantAccountJoin`。
- 历史 HITL 必须保留 Contact snapshot，因此 Contact 后续状态变化不应破坏历史审计。
- 如果 Contact 对应 Account 不属于当前 Workspace，但该 Contact 被当前 Workspace 明确选为 HITL 接收人，则实现上不能假设该 Account 一定有当前 Workspace membership。

## 仍待决策

当一个 Contact 对应的 `Account` 不属于当前 Workspace，但被当前 Workspace 选为 HITL 接收人时，需要进一步明确：

1. 该 Account 是否总是允许查看并填写当前 Workspace 的 HITL 表单，还是需要额外 Contact-scoped permission。
2. 审计、事件流、日志和 UI 中应如何展示“非当前 Workspace member 提交”的事实。
3. 如果该 Account 后续从其来源 Workspace 离开，当前 Workspace 中引用它的 Contact 是否应自动失效。
4. 该类 Contact 的 `source` 应如何命名：例如 `deployment_member`、`enterprise_member` 或其他。

## 暂定实现约束

- `submission_user_id` 可以记录该 Account id，但必须同时记录 Contact snapshot，避免后续误解为当前 Workspace member。
- callback 校验必须确认 provider identity 对应的 Account 与原始 Contact recipient snapshot 匹配。
- 现有基于 `TenantAccountJoin` 的权限 helper 不应直接作为该场景的唯一授权依据。
