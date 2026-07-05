## Why

Feishu PRD 把 HITL 二期的中心问题定义为 `Contact / Human Roster / Recipient / IM + Email` 主动触达，但当前 Dify 的 HITL 仍然只有 Web 表单和 Email 路径。下周一 Demo 至少需要跑通“Dify 账号绑定飞书、HITL 发 IM、IM 填卡、回调回 Dify、继续执行”的纵向链路，因此需要一个既对齐 PRD 核心语义、又尽量复用现有 HITL 配置和代码路径的 CE Demo 方案。

## What Changes

- 在 Dify 内引入一个面向 CE Demo 的最小 `Contact / Human Roster` 兼容层，用脚本把当前 workspace members 导入为可通知联系人；本期不实现 contact 创建、编辑、删除能力。
- 为 Dify 账号增加飞书 OAuth 绑定能力，并把成员联系人上的 IM 身份绑定投影到该账号绑定结果上。
- 继续复用现有 HITL 节点 `member` recipient 配置作为 Demo 的静态联系人来源，将现有 member recipient 解释为对应的 member contact，而不是新增节点配置入口。
- 为 HITL 增加飞书通知通道：已绑定飞书的 member contact 默认走 `IM + Email` 双渠道；未绑定成员、external recipient、动态 email 仍保留现有 email 行为。
- 在飞书支持的字段子集上发送可交互卡片；对不适合卡片承载的表单退化为 IM 内审批链接，而不是让通知链路直接失败。
- 使用飞书官方 SDK 和长连接模式接收卡片交互，回调后复用现有 HITL 提交与 resume 流程继续执行 workflow。
- 增加通知与回调审计记录，帮助 Demo 期间定位“解析到谁、发到哪、为什么失败、谁提交了”。
- 明确 Demo 范围外内容：不做 Slack、不做 SaaS/EE 差异闭环、不做完整 Human Roster / Contact Directory UI、不做 contact 创建/编辑/删除、不做 external contact 的 IM 绑定、不做多人审批规则。

## Capabilities

### New Capabilities
- `hitl-feishu-binding`: 为 Dify 账号提供飞书 OAuth 绑定能力，并把该绑定作为 member contact 的 IM 身份来源。
- `hitl-feishu-delivery`: 在 PRD 的 Contact / Recipient 语义下，把现有 HITL member recipient 解析成可通知联系人，并为已绑定飞书的成员执行 `IM + Email` 双渠道通知。
- `hitl-feishu-resume`: 通过飞书长连接接收卡片动作或链接回流，更新结果状态，并复用现有 HITL resume 链路继续执行。

### Modified Capabilities
- 无

## Impact

- `api/models/`、`api/migrations/`：增加最小联系人投影与飞书消息投递审计所需的持久化结构。
- `api/controllers/console/auth/`、`api/libs/oauth.py`：增加飞书绑定入口和回调。
- `api/services/`、`api/tasks/`、`api/core/workflow/`：把 Contact/Recipient 解析、双渠道通知、飞书回调恢复接入现有 HITL 生命周期。
- `api/commands/`：增加飞书长连接 listener 的独立启动入口，以及 workspace member 导入脚本。
- `api/pyproject.toml`：引入飞书官方 SDK 与长连接 SDK。
- Web 前端：Demo 目标是不改或极少改；若暴露绑定入口，只允许最小调用面，不引入完整的 Contact / Human Roster 管理页。
