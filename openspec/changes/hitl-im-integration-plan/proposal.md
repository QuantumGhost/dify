## Why

Dify 需要一套新的 Contact-based HITL 能力，把人工审批和表单填写路由到实际协作发生的 IM，同时保留 Web UI / CLI / OpenAPI 的发起者处理路径。该变更需要先用飞书企业自建应用在 demo 中跑通闭环，但设计不能变成只服务 demo 的一次性代码。

## What Changes

- 新增 Workspace-scoped `Contact` 对象，用于表达 HITL 接收人；member Contact 关联 Dify `Account`，external Contact 仅包含 `name` 和单个 `email`。demo 阶段提供从现有 Workspace members 创建 Contact 的脚本用于测试和演示数据准备。
- 新增新 HITL `NodeType`、新 `Version` 和新的 runtime 实现；正式路径使用 Contact recipients，不再在节点上配置发送渠道。
- demo 阶段保留一个 transitional compatibility layer：所有前端编排仍使用现有 HumanInput v1 配置面，前端提交的 v1 node config 在后端/runtime 执行前映射为 HumanInput v2 runtime model，并使用新的 v2 runtime 执行。
- 新增 provider-neutral IM adapter 和 app config resolver，支持飞书企业自建 demo，并为 CE/EE 企业自建、Cloud Slack ISV、Cloud 钉钉企业自建预留配置来源边界。
- 新增 member Contact 的 IM identity binding；第一期 service 层只允许一个 active IM provider，但数据库模型允许未来多 provider 并存。
- 新增 HITL runtime 投递逻辑：优先 IM，未绑定 IM 时 fallback 到 email；email 也不可用时 skip，并把状态暂记到节点 `process_data`。
- 新增 IM callback 处理、interaction mapping snapshot、幂等、签名验证、卡片状态更新和异步补偿，并复用已有 Human Input submission/resume 机制。
- 新增 `Allow Current Initiator to Approve`：Console / CLI OpenAPI 使用 `Account`，Web App / Service API 使用对应 `EndUser`。
- 不引入 breaking API change；旧 HITL 后续通过 opt-in 迁移到新 HITL。

## Capabilities

### New Capabilities

- `hitl-contact-management`: 管理 Workspace-scoped Contact、demo member Contact seed script、external Contact，以及 HITL 历史 snapshot。
- `hitl-im-app-configuration`: 管理不同版本下的 IM app config resolution，包括企业自建和 ISV 安装模式；配置来源可来自 deployment config、tenant config 或需要生命周期管理的 ISV install 存储。
- `hitl-contact-im-binding`: 绑定 member Contact 对应的 Dify Account 与 IM provider identity。
- `hitl-contact-form-delivery`: 使用新 HITL node/contact recipients 生成并投递 HITL 表单，包括 demo shim、email fallback 和 initiator approval。
- `hitl-im-form-callback`: 接收、校验并处理 IM 表单提交，将 provider callback 映射回 Dify form submission。
- `hitl-im-workflow-resume`: 基于已校验的 IM 或 initiator submission 恢复暂停中的 HITL workflow execution。

### Modified Capabilities

- None.

## Impact

- Backend API：新增 Contact model/service/repository、IM app config resolver、必要的 ISV install/tenant config 存储、provider-neutral service、controller/webhook endpoint、domain error，以及 workflow/HITL resume 集成。
- Workflow runtime：新增 Contact-based HITL node runtime，不再把新 HITL runtime 与旧 delivery method 配置耦合。
- Frontend Web：正式实现最终需要新增 Contact recipient 配置、Contact 管理和 IM binding/config UI；这些正式 v2 前端配置面不属于 demo 范围。demo 阶段必须复用现有 HumanInput v1 编排界面，最多做极少非结构性调整，并由后端/runtime 负责将 v1 node config 映射到 v2 runtime model。
- 外部系统：飞书企业自建应用用于 demo；CE/EE 使用企业自建应用；Cloud 首期需要支持 Slack ISV 安装和钉钉企业自建应用，并预留其他 provider 的 install mode。
- 数据兼容：不把现有 `TenantAccountJoin` 全量迁移到 Contact 表；demo 只提供从现有 Workspace members 创建 Contact 的脚本。Contact 自动同步、lazy materialization 和正式迁移/投影策略后续单独设计。
- 测试：覆盖 Contact seed/snapshot、app config resolution、binding、delivery fallback、interaction mapping、callback validation、幂等、卡片补偿和 workflow resume。
