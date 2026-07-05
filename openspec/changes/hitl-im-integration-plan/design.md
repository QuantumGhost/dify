## Context

现有 HITL 已有可复用的 runtime 基础：

- `DifyHITLCallback` 在 workflow pause 时创建 `HumanInputForm`、`HumanInputDelivery` 和 `HumanInputFormRecipient`。
- `HumanInputService.submit_form_by_token` 负责 form active/submitted/expired 校验、提交数据规范化，并根据 `workflow_run_id` 或 `conversation_id` enqueue resume。
- workflow resume 已经由现有 task 和 runtime snapshot 机制接管，IM callback 不应直接操作 graph runtime。

新的产品方向与旧 HITL delivery 配置不同：新 HITL 需要新 `NodeType`、新 `Version` 和新的 runtime 实现，节点配置 Contact recipients，而不是配置发送渠道。Contact 是 Workspace-scoped 新对象：member Contact 关联 Dify `Account`，external Contact 只支持 `name` 和单个 `email`。member Contact 可绑定 IM；external Contact 短期只支持 email。

部署版本和 IM app 分发也会影响数据模型：

- CE：只支持 deployment global 的企业自建 IM app。
- EE：首期可只支持 deployment global 的企业自建 IM app；模型预留 tenant override，解析顺序为 tenant override > deployment global。
- Cloud：首期需要支持 Slack ISV install 和钉钉企业自建应用；两种模式不要求同一个 tenant 同时启用。模型需要预留后续 provider 同时支持 ISV 和企业自建的空间。
- demo provider：飞书企业自建应用，事件模式使用 long connection。

当前 demo 的所有前端编排仍必须在现有前端代码中完成，或只做极少非结构性调整。新的 Contact recipient 配置 UI、Contact 管理 UI、IM binding/config UI 和 HumanInput v2 前端配置面不属于 demo 范围。为此需要一个 transitional compatibility layer：前端仍使用现有 HumanInput v1 编排界面并提交 v1 node config；后端/runtime 在执行前将 v1 config 映射为 HumanInput v2 runtime model，并使用新的 v2 runtime 执行。该 compatibility layer 不能成为正式 v2 schema 的长期边界。

## Goals / Non-Goals

**Goals:**

- 用飞书企业自建应用完成 demo 闭环：账号绑定、HITL 表单投递到 IM、IM 侧填写、callback 回 Dify、workflow 继续执行。
- 新增 Contact 模型和 Contact-based HITL runtime，支撑后续从旧 HITL opt-in 升级。
- 避免全量迁移 `TenantAccountJoin` 到 Contact 表；demo 阶段提供一个从现有 Workspace members 创建 Contact 的脚本，用于测试和演示数据准备。
- 复用 `HumanInputForm`、`HumanInputFormRecipient`、`HumanInputService.submit_form_by_token` 和已有 resume 机制。
- 支持原 HITL 表单类型：paragraph、select、file、file-list 和 actions。IM 不支持的 file/file-list 可通过 Web form fallback 完成。
- IM 未绑定时运行时 fallback 到 email；email 缺失时 skip，并把结果暂记到节点 `process_data`。
- 多收件人维持 first valid submission wins；IM 卡片如果允许，应更新状态，更新失败进入异步补偿。
- 实现 `Allow Current Initiator to Approve`，按调用来源识别 `Account` 或 `EndUser`。

**Non-Goals:**

- 正式 v2 前端配置面不属于 demo 范围；demo 前端编排复用现有 HumanInput v1 配置面。
- 不在第一阶段支持多人审批、复杂审批流或外部 IM identity。
- 不把 IM callback 设计成新的 workflow resume 通道。
- 不要求 Cloud 同一 tenant 同时支持 Slack ISV 和钉钉企业自建。
- 不在第一阶段把旧 HITL 自动迁移到新 HITL。

## Decisions

### 1. 使用新的 Contact-based HITL node，而不是扩展旧 delivery method

正式实现新增 HITL `NodeType` 和 `Version`。新 node config 使用 Contact recipients，并增加 `allow_current_initiator_to_approve`。旧 HITL delivery methods 保持现状，后续提供 opt-in migration。

demo 阶段必须增加 transitional compatibility layer：现有前端继续提交 HumanInput v1 node config，后端/runtime 将整个 v1 config 转换为 HumanInput v2 runtime model，再交给新的 v2 runtime 执行。这个 mapping 不只是 recipient mapping；它需要覆盖 demo 所需的 form content、inputs、actions、timeout、member recipients，以及 v2 runtime 所需的 Contact/IM recipient model。

该 compatibility layer 的约束：

- demo 的 workflow/HITL 编排仍通过现有前端 v1 配置面完成。
- demo 不依赖新的 v2 Contact recipient 配置 UI。
- mapping 只作为 demo 和迁移过渡路径存在，不作为正式 v2 schema 的持久设计。
- v2 runtime 是唯一执行目标，不能因为 demo 复用 v1 config 而回退到 v1 runtime。

#### Demo transitional path for this planning slice

为避免 demo 期间前后端边界继续漂移，本期将过渡路径固定为下面 5 步：

1. workflow author 继续只使用现有 HumanInput v1 前端编排界面，配置 form content、inputs、actions、timeout 和当前 v1 支持的 member recipients。
2. workflow draft / publish 继续持久化 v1 node config；demo 不新增新的前端存储 schema，也不要求前端回写 Contact/IM-specific config。
3. workflow runtime 在 pause 创建 form 之前，先把 v1 node config 映射成 v2 runtime model：补齐 Contact recipient lookup、recipient snapshot、initiator approval snapshot，以及 IM inline fields 和 Web fallback fields 的分流结果。
4. delivery 只消费 v2 runtime model：paragraph/select/actions 走 IM inline rendering；file/file-list 保留在同一个 form token 下，通过 Web form link 完成 fallback。
5. callback 和 Web fallback submit 最终都只调用 `HumanInputService.submit_form_by_token(...)`；demo 不新增第二条 resume 通道，也不允许 v1 runtime 与 v2 runtime 并存执行同一个 form。

这个过渡路径的收敛条件也需要提前写清楚：一旦正式 v2 Contact recipient 配置 UI 和新 node schema 可用，就应移除 v1-to-v2 compatibility mapping，而不是继续把 v1 config shape 当作长期输入契约。

#### Concrete demo form sample

为了让 1.3 的 demo 验证范围可执行，本期固定使用下面这类混合表单作为样例：

```json
{
  "title": "Review customer escalation package",
  "description": "Validate the escalation details before the workflow continues.",
  "inputs": [
    {
      "type": "paragraph",
      "variable": "review_summary",
      "label": "Review summary",
      "required": true
    },
    {
      "type": "select",
      "variable": "risk_level",
      "label": "Risk level",
      "required": true,
      "options": [
        { "label": "Low", "value": "low" },
        { "label": "Medium", "value": "medium" },
        { "label": "High", "value": "high" }
      ]
    },
    {
      "type": "file",
      "variable": "signed_approval",
      "label": "Signed approval screenshot",
      "required": false
    },
    {
      "type": "file-list",
      "variable": "supporting_files",
      "label": "Supporting evidence",
      "required": false
    }
  ],
  "actions": [
    { "id": "approve", "label": "Approve" },
    { "id": "request_changes", "label": "Request changes" }
  ],
  "timeout_minutes": 1440
}
```

这个样例在 demo 中的预期行为如下：

- IM card 内联渲染 `paragraph`、`select` 和 `actions`，用于验证 IM 内可直接填写和提交的最小闭环。
- card 同时展示 Web form entry，用于补齐 `file` 和 `file-list`；两条路径共用同一个 form token 和同一套 snapshot / authorization 语义。
- 如果要验证“IM 可直接提交”的 happy path，就保持 `signed_approval` 和 `supporting_files` 为 optional。
- 如果要验证“必须走 Web fallback”的路径，就把 `signed_approval.required` 改为 `true`；此时 IM card 仍可展示上下文和可内联填写字段，但不能把缺失 upload 的 IM-only 输入视为最终有效提交。

替代方案是在旧 HITL 上新增 `DeliveryMethodType.IM`。该方案会把新产品模型继续绑定到旧 delivery channel 配置，不符合“节点配置 Contact 接收者”的目标。

### 2. 引入 authoritative Workspace-scoped Contact，并保留 runtime snapshot

Contact 模型建议包含：

- `tenant_id`
- `type`：`member` 或 `external`
- `account_id`：member Contact 使用，external 为空
- `name`
- `email`
- `status`
- `source`：例如 current workspace member、EE deployment member、manual external
- `created_at`
- `updated_at`

`Contact` 是 authoritative workspace recipient row，而不是运行时按 membership 临时 materialize 的投影。对于 member Contact，`tenant_id + account_id` 对应唯一 authoritative row，`status` 在该 row 上流转，而不是通过追加历史 member rows 表达状态变化。member Contact 的 profile 读路径以 `Account` 为准；`Contact.name/email` 只作为 bootstrap/fallback cache，用于 bootstrap 阶段和缺失 `Account` 资料时的降级读取，不构成 member profile 的 source of truth。external Contact 的 profile 由 `Contact` 自身持有。demo 阶段不做一次性全量迁移，而是提供一个从现有 Workspace members 创建缺失 member Contact 的 bootstrap 脚本，用于测试和演示数据准备。该脚本只负责补齐缺失 Contact，不承担自动同步、lazy materialization、projection fallback、重新激活或持续 reconciliation 的职责；这些策略后续单独设计。

HITL runtime 必须保存 Contact snapshot，至少包含 `contact_id`、`type`、`account_id`、`name`、`email`、`source` 和当时的 provider/binding 信息。这样 Contact 后续删除、失效或资料变化不会破坏历史表单、审计和排障。

### 3. IM binding 绑定 Account 和 credential scope，但授权入口是 Contact recipient

第一期只有 member Contact 可绑定 IM。binding 不强制引用统一的 `app_installation_id`，而是保存一组稳定的 credential scope 字段，用来描述“这个绑定属于哪套 IM app 配置”。这样 CE/EE 的 deployment global 自建应用可以直接来自配置文件或 secret manager，不必为了少量部署级配置创建 DB row；Cloud Slack ISV、未来 tenant self-built config 等需要生命周期管理的场景再由 resolver 映射到 DB 存储。

binding 表面向 `Account`、credential scope 和 provider identity：

- `account_id`
- `provider`
- `install_mode`：`self_built` 或 `isv`
- `scope_type`：`deployment` 或 `tenant`
- `scope_id`：例如 `deployment` 或具体 `tenant_id`
- `provider_workspace_id`
- `provider_user_id`
- `provider_union_id`
- `status`
- `created_at`
- `updated_at`

这组字段替代第一阶段的 `app_installation_id` 外键。后续如果引入统一 install/config 表，可以通过 `(provider, install_mode, scope_type, scope_id, provider_workspace_id)` 映射或迁移到外键，但当前业务代码应依赖 resolver 返回的运行时 app context，而不是直接依赖某张安装表。

DB 允许多 provider，为未来同一 Account 绑定飞书、钉钉、Slack 留空间。第一期“一种 active IM”由 service 层事务校验实现，因为 MySQL 不能依赖 partial unique constraint。

callback 授权不能只看 Account membership，必须确认 callback provider user 对应的 Account 是当前 form recipient snapshot/Contact 授权的接收人。EE 跨 Workspace Contact 的细节仍单独记录在 `ee-cross-workspace-contact-question.md`。

### 4. IM app config 按版本和 install mode 解析

引入 provider app config resolver 和运行时 value object，例如 `IMAppContext`。它至少区分：

- `provider`
- `install_mode`：`self_built` 或 `isv`
- `scope_type`：`deployment` 或 `tenant`
- `scope_id`：`deployment` 或具体 `tenant_id`
- `provider_workspace_id`
- provider credentials / token fields（仅保留运行时真正需要的部分）
- token refresh state
- install status

配置来源不要求统一落库：

- deployment global self-built app 可以来自 `dify_config`、env 或 secret manager。
- tenant override self-built app 可来自独立的 tenant self-built config 存储。
- ISV install 因为有 install/uninstall/token refresh 生命周期，通常需要独立的 installation 存储。

这里需要额外固定两个边界，避免 demo 期间为了赶进度把模型揉在一起：

- tenant self-built override 和 lifecycle-managed install 不共用同一张 provider-neutral 配置表；前者持有 self-built credential / callback material，后者持有 install status 与 token lifecycle。这样 future Slack ISV、钉钉企业自建和飞书企业自建不会把 nullable provider-specific 字段继续堆到同一张“万能表”里。
- resolver 必须显式区分 `found`、`not_found` 和 `store_unavailable`。只有明确的临时兼容场景（例如当前进程没有绑定 Flask app context，或新表尚未迁移完成）才允许 fallback 到 deployment-global config；真实的持久化错误不能静默吞掉再伪装成“没有 tenant override”。
- management API 也沿用这条分层：tenant self-built config 使用独立写/删/读接口，installation lifecycle 使用独立只读接口返回 redacted status；不要用一个“统一 IM app config API” 假装所有 provider 都有相同的 install/write path。

运行时解析：

- CE：deployment global self-built。
- EE：tenant override self-built > deployment global self-built；第一期可以只实现 deployment global，但 schema/service 预留 override。
- Cloud：Slack 使用 ISV install；钉钉使用 tenant self-built。两者无需同一 tenant 同时启用。
- Demo：飞书使用 self-built app config，且 phase-1 demo 要求 long connection 模式，不走 webhook 模式。

### 5. HITL delivery 以 Contact recipient 为中心

新 runtime 根据 Contact recipients 生成 form recipients 和 snapshots：

- member Contact：如果有 active IM binding，发送 IM；无 binding 时 fallback 到 email；如果 email 也不可用则 skip。
- external Contact：只发送 email。
- `Allow Current Initiator to Approve`：为当前发起者增加可提交路径，但不等同于 Contact recipient。

fallback/skip 状态暂存到节点 `process_data`，后续可迁移到更稳定的 execution extra content 或 delivery status model。

### 6. IM callback 只提交 form，不直接 resume workflow

callback controller 推荐放在 `api/controllers/trigger/human_input_im.py` 或同等外部 webhook namespace。处理顺序：

1. 按 provider 和 app config 校验 signature、timestamp、challenge。
2. 解析 callback，拿到 provider user、provider event id、message/action private metadata。
3. 查找 IM message correlation、form recipient、Contact snapshot 和 interaction mapping snapshot。
4. 校验 provider user 对应的 Account / binding 与原始 Contact recipient 匹配。
5. 使用 interaction mapping snapshot 将 provider component/action id 翻译为 Dify 的 `selected_action_id` 和 `form_data`。
6. 调用 `HumanInputService.submit_form_by_token(...)`，写入 `submission_user_id` 或 `submission_end_user_id`。
7. 更新 IM message status；如果 provider card update 失败，写入补偿任务。

这里再明确一条测试边界，避免后续把 adapter 责任错误塞回 provider-neutral core：

- signature / timestamp / challenge verification 归 provider adapter 或 transport seam 所有，不作为 provider-neutral facade 的职责；
- provider-neutral core 从“已验证、已解析的 provider event”开始工作，负责 binding/context 校验、duplicate event 幂等、submission outcome 映射，以及 card compensation enqueue。

发送 IM message/card 时必须持久化 interaction mapping snapshot。该 snapshot 是 callback 翻译的唯一可信来源，用于把 provider-local component/action id 映射到 Dify form 语义：

```json
{
  "schema_version": 1,
  "inputs": {
    "provider_component_reason": {
      "output_variable_name": "reason",
      "type": "paragraph"
    }
  },
  "actions": {
    "provider_action_approve": {
      "action_id": "approve"
    }
  }
}
```

callback payload 不应直接携带并决定 Dify 的 `action_id` 或 `output_variable_name`。即使 callback signature 有效，也只能证明 payload 来自 provider，不能证明其中的 Dify 字段名被当前 form recipient 授权。callback 中出现 snapshot 不认识的 component/action id 时，系统必须拒绝该提交。

这个 snapshot 同时解决一致性问题：如果卡片发送后 HITL node config、form definition 或 provider card rendering 逻辑发生变化，旧卡片的 callback 仍按发送当时保存的 mapping 解释，而不是读取最新配置重新解释。

### 7. Initiator approval 使用来源特定 actor

`Allow Current Initiator to Approve` 的 actor 解析规则：

- Console：`Account`
- CLI OpenAPI：`Account`
- Web App：`EndUser`
- Service API：通过 API 提交的 `EndUser`

该路径仍应复用 Human Input submission service。它只是新增一个 authorized submission actor，不改变 first valid submission wins。

### 8. 幂等在 callback event、form submission、card update 三层处理

Provider callback 层按 provider event id 去重。Form submission 层保证 form 只从 waiting 转 submitted 一次，避免并发 callback 重复 enqueue resume。Card update 层使用异步补偿，workflow 不等待卡片更新成功。

## Risks / Trade-offs

- [Demo 使用 v1 config compatibility mapping] → 明确标注 transitional path，正式新 HITL schema 不依赖旧 v1 config shape；测试必须证明 v1 frontend-submitted config 最终走 v2 runtime。
- [Contact 不做全量迁移] → demo 使用显式 seed script 准备 Contact 测试数据；Contact 自动同步和 lazy materialization 后续单独设计，避免把 demo 脚本误当正式迁移方案。
- [MySQL 无 partial unique constraint] → 多 provider 数据模型靠普通唯一键保护 provider identity；第一期 active provider 限制放在 service 层。
- [EE 跨 Workspace Contact 权限复杂] → 单独保留待决文档；实现时基于 Contact recipient 授权，不假设存在当前 workspace membership。
- [IM file/file-list 支持不一致] → 保留 Web form fallback，IM card 只内嵌 provider 能稳定支持的字段。
- [卡片状态更新失败] → workflow 不阻塞，异步补偿并保留 operator 可排障状态。

## Operator Troubleshooting Path

本期 operator 排障以结构化日志和已有持久化状态为主，不新增独立后台页面。排障入口按下面顺序进行：

1. 先用 `tenant_id + form_id` 或 `workflow_run_id / conversation_id` 过滤结构化日志，确认当前问题落在 seed、binding、delivery、callback 还是 resume enqueue 路径。
2. 如果问题发生在投递阶段，再读取对应 node execution 的 `process_data.human_input_delivery.recipient_statuses`；该状态暂存 delivery fallback / skip / IM failure 的 operator 视图，并补齐 `recipient_id`、`contact_id`、`provider`、`provider_message_id`、`provider_event_id`、`workflow_run_id`、`conversation_id` 等标识。

具体 failure mode 的定位路径如下：

- Contact missing
  先看 `seed-workspace-contacts` command / bootstrap logs 中的 `tenant_id`、`member_account_ids`、`contact_ids`。如果 delivery 日志出现 `skipped_missing_contact_snapshot` 或 `skipped_missing_account`，说明运行时 recipient snapshot 本身不完整，需要回查 form 创建链路，而不是继续重试 callback。
- Delivery fallback / skip
  优先查看 `process_data.human_input_delivery.recipient_statuses`。`fallback_email` 表示 member Contact 未绑定 IM，已改走 email；`skipped_email_unavailable`、`skipped_missing_email`、`skipped_no_email` 表示 fallback 不成立；`im_failed` 说明 provider send 已拒绝并会在日志里带 `correlation_id`、`provider_message_id`、`error_reason`。
- Callback rejected
  查看 callback logs 中同一 `provider_event_id`、`correlation_id`、`interaction_id` 的记录。`validation_error` 对应 provider identity / interaction mapping / form payload 校验失败；若是 duplicate callback，会明确记录 duplicate event，不应再继续人工重放同一个 provider event。
- Form expired
  callback 或 submission logs 出现 expired 路径时，优先核对 `form_id`、`workflow_run_id`、`conversation_id`、`expiration_time` 所对应的 form 生命周期。此类问题应重建新的表单或重新触发 workflow pause，而不是强推 resume。
- Card update failed
  当前卡片更新失败不阻塞 workflow resume。先根据 `correlation_id`、`provider_message_id`、`provider_event_id` 查 callback success log，再查看 compensation enqueue log；如果只有 submission success 没有 compensation enqueue，说明问题在补偿入队。
- Resume enqueue failed
  通过 `workflow_run_id` 或 `conversation_id + form_id` 查 `HumanInputService` 的 enqueue logs。`Enqueued ... resume task` 表示已交给 Celery；`Failed to enqueue ...` 表示任务未入队，需要排查 broker / worker；`App is missing` 或 `App mode does not support resume` 表示是数据或模式问题，不是队列问题。

## Migration Plan

1. 新增 Contact、IM app config resolver、必要的 ISV install/tenant config storage、IM binding credential scope、IM message correlation 和必要 snapshot 字段。
2. 为 demo 增加从现有 Workspace members 创建 Contact 的 seed script。
3. 增加 provider-neutral adapter、config resolver、binding/delivery/callback service。
4. 为 demo 接入飞书 self-built adapter，并实现 HumanInput v1 config 到 HumanInput v2 runtime model 的 compatibility mapping。
5. 增加新 HITL node runtime 和 Contact recipient schema；后续前端接入正式配置面。
6. 后续单独设计 Contact 自动同步、lazy materialization、正式迁移/投影策略，以及 opt-in migration。
7. 回滚策略：关闭 IM app config 或 feature flag；旧 HITL、Web/Email submission 和现有 workflow resume 不受影响。

## Post-Demo Follow-Ups

本期 demo slice 之后，后续实现需要按下面 4 组主题继续收敛，避免把当前过渡路径长期产品化：

1. 正式新 NodeType 前端
   需要新增 Contact recipient 配置 UI、Contact 管理 UI、IM binding/config UI，以及对应 i18n 文案与交互稿。当前 demo 明确不包含这部分。
2. v1-to-v2 compatibility mapping 收敛计划
   当前 runtime 仍接受前端提交的 HumanInput v1 配置，并在执行前映射到 Contact-based v2 runtime model。正式 v2 schema 与前端可用后，应删除这条 mapping，而不是继续把 `delivery_methods` / v1 shape 当长期输入契约。
3. 旧 HITL opt-in migration
   需要单独设计旧 HITL 到新 Contact-based HITL 的 opt-in 升级路径，包括草稿/已发布 workflow 的迁移界面、回滚策略，以及 runtime snapshot 兼容边界。
4. 更多 provider 与 EE 跨 Workspace Contact 决策
   需要补齐 Slack ISV install/uninstall/token refresh 的真实 provider path、钉钉 tenant self-built 的实际 resolver/runtime 接入，以及 EE 跨 Workspace Contact 的授权、失效和审计语义。

## Open Questions

- 截至 2026-07-05，当前 workspace/context 内没有可直接复核的外部飞书 wiki PRD 或 Figma HITL node artifact；本次 planning/doc slice 只能依据仓库内 OpenSpec 文档和当前分支已有实现上下文推进。
- 上述外部产物一旦可访问，需要重点复核 3 个点：demo 表单文案与字段顺序、HITL node 交互稿是否假设了新的 recipient/config UI、file/file-list 的 Web fallback 文案和入口是否与本设计一致。
- EE 跨 Workspace Contact 的最终授权和失效策略仍需确认，详见 `ee-cross-workspace-contact-question.md`。
- 飞书互动卡片对 file/file-list 的最终体验是否只走 Web fallback，还是需要后续原生支持。
- `process_data` 是否是 fallback/skip 状态的长期存储位置，还是只作为第一期暂存。
- Contact 自动同步、lazy materialization、正式迁移/投影策略后续单独设计，不属于 demo 范围。
