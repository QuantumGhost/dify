# HITL IM Implementation Planning

## 目标

在 `2026-07-06`（下周一）之前，交付一个可以稳定演示的 HITL + IM 最小闭环，并且实现路径要能自然演进到后续正式版本，而不是临时 Demo 代码。

## 下周一前必须完成的闭环

1. Dify 账号与一个 IM 账号建立绑定关系。
2. Workflow 在 Human Input 节点暂停后，可以把表单发送到 IM。
3. 用户优先在 IM 卡片内直接完成表单填写或审批动作。
4. 只有当表单能力超出 IM 卡片能力时，才降级为“卡片 + 安全链接”。
5. IM 回调回 Dify 后，复用现有 HITL resume 链路继续执行 workflow。

## 关键约束

- 不做一次性 Demo hack。
- 不绕开现有 `HumanInputService.submit_form_by_token(...)` 和 workflow resume 机制。
- 不把 IM provider 细节直接写进核心 workflow runtime。
- 不在节点 DSL 中写入 provider secret、bot token、signing secret 等部署级配置。
- 允许在下周一前只做一个 IM provider，但抽象必须支持后续增加第二个 provider。
- IM 默认策略必须是 **card-first**，不能直接把链接当作默认实现。
- IM 内联表单是否可用，必须由 provider capability 决定，而不是由节点配置硬编码。
- demo 阶段允许 Feishu `app_id / app_secret` 通过 environment variable 提供。
- 正式方案必须支持 **per-tenant** 的 IM provider config，不能把 env 方案固化成长期架构。
- demo 阶段可直接读取 `/Users/qg/workspace/langgenius/im-integration/feishu.env`。
- 当前已确认该文件至少包含：
  - `LARK_APP_ID`
  - `LARK_APP_SECRET`
  - `LARK_EVENT_MODE`
- IM provider 接入必须**优先使用官方 SDK**，只有官方 SDK 缺失必要能力时才允许补手写 HTTP 调用。

## 当前代码基线

### 已有能力

- HITL runtime、form token、submit、resume 链路已存在。
- `HumanInputForm` / `HumanInputDelivery` / `HumanInputFormRecipient` 已经提供了 paused task、delivery、recipient 的基础数据模型。
- `approval_channels` / `form_token` / `display_in_ui` 语义已建立，CLI E2E 已覆盖“外部渠道不可直接 resume”的场景。
- Console / Service API / OpenAPI 的 form fetch + submit 边界清晰。
- Email 已经是一个真实 delivery provider，可作为 IM provider 的抽象模板。

### 明显缺口

- 后端 `DeliveryMethodType` 只有 `WEBAPP` / `EMAIL`。
- 前端 Slack 只是 `COMING SOON`，后端没有 Slack / Lark delivery adapter。
- 没有 IM integration config、IM account binding、IM callback endpoint。
- 没有 provider-level delivery record / provider message id 持久化。
- 没有 Human Roster / Contact Directory 的正式数据模型和管理界面。

## 外部需求结论

### 已确认

- 飞书 PRD《HITL(NEW) 二期：IM 通知与 Human Roster PRD》已阅读。
- 首个 provider 已确定为 **Feishu/Lark**。
- `file / file-list` 基本不具备可靠的 IM 卡片内提交能力，默认视为 **link fallback only**。
- 飞书卡片官方能力已补充核对：
  - 支持 Card JSON 2.0、`form` 容器和交互组件。
  - 支持 `input` 等卡片内输入控件与 `card.action.trigger` 回调。
  - callback 需要快速应答，卡片更新与交互有平台时效约束。
  - 官方 Python Server SDK 支持 API 调用、事件处理、回调处理，并提供 **长连接** 和 **Webhook** 两种回调接入方式。
- 产品长期方向包括：
  - Human Roster / Contact Directory
  - IM identity binding
  - 默认 IM + Email 双通道
  - delivery records / resolution records
  - current initiator approval

### 未确认

- 提供的 Figma URL 当前无法通过本次接入身份读取，无法直接核对设计稿中的卡片细节与页面排版。
- 因此本计划对 UI 细节只基于飞书 PRD 与现有仓库结构做保守拆分。

## 推荐路线

### 推荐方案

采用“**通用 IM 抽象先落地，首个 provider 先做 Feishu/Lark，并以 card-first + official SDK first + non-webhook first 为默认策略**”。

原因：

- 对内部 Demo 成功率最高，联调对象和演示环境更容易准备。
- 当前需求明确允许 `Slack 或飞书` 二选一。
- 真正有长期价值的是抽象边界，而不是先做哪一个 provider。
- 后续如果业务要求优先对齐 SaaS 路线，可以在相同抽象下补 Slack provider，而不推倒重来。

### 可替换项

如果后续要补 Slack / Teams / 企业微信，只替换 provider 实现与 capability profile，其余数据边界不变。

## 下周一前的功能切片

### 必做

- 单 provider IM integration config
- Workspace member 级别的 IM binding
- Human Input 节点可选“IM delivery”
- IM card renderer / callback adapter / form submit callback
- provider config source abstraction
- provider ingress mode abstraction
- 基于现有 `form_token` 的一次性提交与幂等保护
- 最小 delivery record
- 尽可能完整的 provider 测试链路

### 首切字段范围

- `paragraph`
- `select`
- `user_actions`
- 简单文本输入

### 首切默认降级字段

- `file`
- `file-list`

说明：

- `paragraph` 必须进入首切实现。
- 当前 Dify `paragraph` 在 Web 端语义是多行 `Textarea`，而飞书官方 `input` 组件文档摘要强调的是单行文本输入，因此不能直接假定交互体验 100% 等价。
- `file / file-list` 已明确视为 IM 卡片不支持，不进入 inline card 范围。
- 首切实现必须让 provider 基于能力判断：
  - 可以安全内联时，走卡片内联表单。
  - 语义或交互不等价时，走“卡片摘要 + 链接补充填写”。
- 对 `paragraph` 而言，要区分：
  - **card content rendering**：必须支持，可通过飞书卡片 markdown / rich text 渲染。
  - **card inline submission UX**：需要按飞书输入组件实际能力实现，不预设与 Web 的 multiline editor 等价。

### 明确不进首切

- Global Contact Directory
- 完整 Human Roster 管理
- External contact 正式管理
- 多 provider 并存
- Workspace override
- Notification center
- DSL import / export remapping
- 群聊通知
- IM 文件上传表单
- 多阶段卡片向导式复杂表单

## IM 抽象边界

### 1. Provider Capability Profile

每个 IM provider 必须声明自己的交互能力，而不是让调用方猜测：

- 是否支持卡片内输入
- 支持哪些字段类型
- 是否支持单次提交多字段
- 是否支持更新原卡片状态
- 是否支持用户身份回传
- callback 时效和签名校验规则
- config source requirements

### 2. Provider-neutral Form Model

HITL 运行时先把表单归一化为 provider-neutral model，再交给 provider renderer。

建议至少拆成：

- task meta
- field schema
- action schema
- default values
- expiration / submit policy

### 3. Render Decision

provider 不能只负责“把消息发出去”，还要负责决定：

- `inline_card`
- `summary_card_with_link`

判断标准来自 capability profile，而不是 workflow DSL。

### 4. Callback Translator

provider callback 先翻译为统一的 submission payload，再进入：

- signature verification
- provider message lookup
- submission idempotency
- `HumanInputService.submit_form_by_token(...)`

### 5. Provider Config Store

provider config 读取必须再抽一层，避免业务代码直接依赖 env 或数据库：

- `EnvBackedProviderConfigStore`
- `TenantScopedProviderConfigStore`

下周一前可以先实现前者，但调用方只依赖统一接口，例如：

- by tenant id resolve current provider config
- provider enabled / disabled
- app id / secret / verification token / encrypt key lookup

### 6. Provider Ingress Mode

provider 的“接收交互/事件”的入口也必须抽象，而不是把 webhook 写死：

- `WebhookIngressAdapter`
- `LongConnectionIngressAdapter`
- `PollingIngressAdapter`

下周一前的建议实现：

- **Feishu 具体实现优先官方 SDK 的 long connection**
- **接口层同时支持 webhook 抽象**
- **future-friendly 地预留 polling 抽象**

原因：

- SaaS / 无状态部署更偏向 webhook。
- 企业内网部署更偏向不暴露公网 webhook。
- 对 Feishu 首实现而言，官方 SDK 的 long connection 比手写 REST 轮询更贴近官方接入模型。
- `long_connection / webhook / polling` 的差异属于 provider 接入模式，不应泄漏到 HITL 业务层。

建议统一入口能力：

- receive provider interaction envelope
- ack / checkpoint semantics
- normalize to provider-neutral interaction event
- hand off to callback translator / submit pipeline

### 7. Official SDK Usage Policy

首实现必须优先使用官方 SDK 提供的能力：

- API client
- token management
- event / callback handling
- card callback dispatch

当前推荐的官方 Python SDK 组合：

- `lark-oapi`
  - 负责 OpenAPI 调用
  - 适合消息发送、卡片发送、用户信息查询等服务端 API
- `lark-channel-sdk`
  - 负责新的 Channel / 长连接接入
  - 适合非 webhook 的事件、消息、卡片交互回流

只有在以下场景才允许手写 HTTP：

- 官方 SDK 没有覆盖该 API
- 官方 SDK 的能力和当前 Python 版本 / 运行模型存在明确不兼容
- 我们需要的行为官方 SDK 无法表达，且已有验证

## 测试策略

飞书 callback 难以做严格端到端自动化，因此需要把 provider 测试拆层做全：

### 1. Pure unit tests

- capability decision
- card rendering
- provider config resolution
- signature verification
- callback payload translation
- submission idempotency

### 2. Fixture-based contract tests

- webhook envelope fixtures
- card action payload fixtures
- unsupported-field fallback fixtures
- provider error payload fixtures

### 3. Local simulation tests

- 用本地 fixture 驱动 provider callback controller
- 覆盖 `send -> receive payload -> normalize -> submit_form_by_token` 主链

### 4. Manual smoke checklist

- 真实飞书消息发送
- 真实卡片点击/填写
- 真实回调打回 Dify
- workflow resume

说明：

- 自动化测试不追求完全替代飞书联调。
- 但业务链路中的每一层转换都必须可单独验证。

## 设计原则

1. 继续把 `HumanInputForm` 当作当前 HITL task 的 authoritative aggregate，不在下周一前再造第二套 task 主模型。
2. 新增的 IM 能力通过 provider abstraction 挂到 delivery 层，而不是写进 graph runtime。
3. callback 只负责鉴权、反查、归一化、提交，不直接操纵 workflow state。
4. 绑定关系与 provider config 必须是部署 / workspace / account 级配置，不进入 workflow DSL。
5. 先支持 workspace member 绑定，Human Roster 可以在此基础上后补为显式模型。
6. 对 IM 而言，“能否卡片内联”是 provider capability 问题，不是业务层特殊分支。
7. link fallback 是降级路径，不是默认路径。
8. demo 使用 env config 只是 config source 的临时实现，不是长期配置模型。
9. `long_connection / webhook / polling` 是 provider ingress mode 问题，不是 HITL 流程分支。
10. 首选官方 SDK，不重复手搓 provider 协议细节。
