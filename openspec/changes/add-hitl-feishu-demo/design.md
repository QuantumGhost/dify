## Context

通过 `lark-cli docs +fetch` 读取的 Feishu PRD 明确把二期能力组织为四层概念：

- `Contact`：可通知或审批的人
- `Human Roster`：当前 workspace 可被 HITL 选择的联系人集合
- `Recipient`：运行时真正收到通知或可提交的人
- `IM + Email`：默认双渠道触达

而当前 Dify 的实现边界是：

- HITL 已经有稳定的 `form -> recipient token -> submit -> resume` 主链路。
- 现有 workflow 节点静态收件人配置是 `member` / `external` 为中心的 email delivery 结构，不是 Contact / Roster 结构。
- Web 前端没有可直接复用的 Human Roster / IM Integration 管理面。
- 用户的额外要求又进一步收紧了本次变更：
  - 只做 CE Demo。
  - 只做飞书，优先长连接。
  - 尽量不改前端，现有 HITL 节点配置继续作为配置源。
  - `member recipient` 视作 `member contact`。
  - Contact 的创建、编辑、删除流程都不做，初始化只能用脚本导入当前 tenant members。
  - Monday 之前至少交付“账号绑定、IM 发卡、IM 提交、回调恢复”的闭环。

因此，本设计不是完整交付 PRD，而是做一个“按 PRD 核心语义切一条最短纵向路径”的 Demo 方案。

## Goals / Non-Goals

**Goals:**

- 在 Dify 内部落一个最小可用的 `Contact / Human Roster / Recipient` 兼容层，足够支撑 CE Demo。
- 通过一次性导入脚本完成 member contact 初始化，而不是引入 contact 编辑工作流。
- 为 workspace member 提供飞书 OAuth 绑定能力。
- 不修改现有 HITL 节点配置模型，继续从现有 `member recipient` 配置出发。
- 对已绑定飞书的 member contact 实现 `IM + Email` 双渠道通知。
- 用飞书官方 SDK 和长连接模式接收交互，并复用现有 HITL 提交流程恢复执行。
- 对通知、回调、恢复路径保留足够的审计和错误定位信息。

**Non-Goals:**

- 不实现完整 Human Roster / Global Contact Directory UI。
- 不实现 contact 创建、编辑、删除 API 或 UI。
- 不实现 Slack、Teams、Discord、钉钉、企微。
- 不实现 SaaS / EE 的正式部署形态差异。
- 不实现 external contact 的 IM 绑定。
- 不实现多个 IM、群聊、会签、通知偏好、通知中心。
- 不让动态 email 变量反查或生成 Contact 实体。
- 不为本次 Demo 改造现有 workflow 节点的前端配置交互。

## Decisions

### 1. 用最小的 member-contact 投影对齐 PRD，而不是直接跳过 Contact 语义

PRD 的核心对象是 Contact/Human Roster，不是裸 `Account`。但当前 Demo 又明确不做 Contact 编辑能力，因此本次采用最小化方案：

- 为 workspace 引入最小的 member-contact 持久化模型。
- 用脚本把当前 tenant members 导入为 contacts。
- 在 CE Demo 中，当前 workspace 的 member contacts 就是该 workspace 的 Human Roster。
- 不提供 contact 创建、编辑、删除入口；导入结果只作为运行时通知与审批解析的数据底座。

这样做的原因：

- 符合 PRD 对 CE 的默认行为：“workspace members 默认显示在 Human Roster 中”。
- 不需要现在就实现管理页、搜索页、跨 workspace 目录，也不会把未来的 PRD 路径堵死。
- 比直接在运行时只看 `TenantAccountJoin` 更稳，因为 Contact 成为了显式对象，后续外部联系人、状态、审计都能接进来。

备选方案：

- 完全不引入 Contact，直接把 `member recipient` 当作 `Account`。被拒绝，因为这会让本次方案与 PRD 的核心概念脱节，后续还得再做一次语义迁移。
- 直接实现完整 Human Roster / Contact Directory UI。被拒绝，因为前端与数据建模改动超出 Demo 目标。

### 2. Member contact 的飞书绑定存到账号集成上，再投影回 Contact

本次只处理 member contact，因此 IM binding 不单独挂在 Contact 表上，而是复用账号侧外部身份绑定能力：

- Dify account 发起飞书 OAuth 绑定。
- 绑定结果存为账号级 provider 映射。
- member contact 通过 `account_id` 读取该映射，视作自己的 IM identity。

这样做的原因：

- member contact 与 Dify account 在 Demo 中是一对一关系。
- 这条路径最短，不需要为 external contact 提前引入另一套绑定表。
- 仍然满足 PRD 中“联系人绑定一个 IM 身份”的语义，只是绑定存储落在 member contact 对应的账号上。

备选方案：

- 单独建 contact binding 表。被拒绝，因为对只含 member contact 的 Demo 没有实际收益。
- 只在 runtime 临时填写 open_id，不做持久化。被拒绝，因为无法支撑可重复演示与审计。

### 3. 继续把现有 `member recipient` 当配置源，通过兼容映射解释为 `member contact`

当前 workflow 节点已经有静态 `member` recipient 配置。为减少前端和 schema 改动，本次不新增 `Human Roster` 选择器，也不新增 `feishu` delivery method。运行时做一层兼容映射：

- `member recipient.reference_id` 继续保存当前成员账号 id。
- 通知阶段将该账号 id 解析成 workspace 内导入好的 member contact。
- member contact 再决定是否有 IM binding，以及走什么通知通道。

这样做的原因：

- 满足“现有 Member Recipient 对应到 Member Contact”的用户要求。
- 不用触碰 workflow 节点配置 UI 和序列化格式。
- 后续即使引入正式 Human Roster UI，也可以把这层兼容映射替换掉，而不是返工本次通知与恢复链路。

备选方案：

- 现在就改节点配置，让它直接存 contact id。被拒绝，因为需要前端与旧 DSL 兼容迁移。

### 4. 按 PRD 保持 `IM + Email` 双渠道，而不是用 IM 替换 Email

PRD 明确要求“默认通过 IM + Email 双渠道触达；Email 默认不可关闭”。因此本次 Demo 的通知规则如下：

- 已绑定飞书的 member contact：发飞书 + 发 email。
- 未绑定飞书的 member contact：只发 email。
- external recipient / one-time email / dynamic email：继续只发 email。

这样做的原因：

- 与 PRD 一致，不需要再做“Demo 是否只发 IM”的产品决策。
- 技术上是对现有 email pipeline 的增量扩展，而不是替换。
- Monday demo 主要展示 IM，email 可以作为旁路和 fallback 保留。

备选方案：

- 对已绑定成员只发 IM。被拒绝，因为与 PRD 冲突，而且会改变现有 Email 兜底语义。

### 5. 卡片优先，字段超出能力时退化为 IM 链接

根据 PRD 与用户补充要求，本次飞书消息优先走卡片内审批，但只强支持：

- `paragraph`
- `select`
- confirm / cancel actions

当表单包含本次不支持的字段（如 `file` / `file-list`）时：

- 不发送半残卡片。
- 改为发送飞书通知消息，其中包含指向现有独立 Web HITL 表单的审批链接。

这样做的原因：

- 符合“card-first，超出能力才降级链接”的路径。
- 现有 Web 表单与 token 提交流程已经成熟，降级链路很便宜。
- 这样即使 workflow 作者没有严格控制字段子集，也不会让 IM 通知整条失败。

备选方案：

- 发现不支持字段就完全不发 IM。被拒绝，因为会让 IM 通知在非理想配置下直接失效，不利于 Demo。

### 6. 飞书长连接 listener 独立于 Web worker 进程

飞书回调不走公网 webhook 主路径，采用独立 listener 进程：

- 使用官方长连接 SDK。
- 通过独立 CLI 命令启动。
- 负责接收卡片动作、完成身份映射与表单提交。

这样做的原因：

- 当前 API 服务是 Web 请求进程模型，把长连接放进去会带来重复连接和生命周期混乱。
- 独立命令更符合 Demo 部署与排错习惯。
- 后续若需要拆成单独 deployment，路径清晰。

备选方案：

- webhook-only。被拒绝，因为用户明确偏好长连接。
- app 启动时隐式拉起 listener。被拒绝，因为进程模型不可控。

### 7. 回调继续复用现有 recipient-token 提交流程

飞书卡片提交后不直接修改 workflow 状态，而是：

1. 根据飞书操作者身份解析到 Dify account。
2. 根据 `form_id + account_id` 找到对应的 member recipient。
3. 取该 recipient 的现有 `access_token`。
4. 调用现有 `HumanInputService.submit_form_by_token(...)`。

这样做的原因：

- 现有 token 提交流程已经包含活跃性校验、动作校验、重复提交保护和 resume 逻辑。
- IM 回调只需要解决“如何定位对的人和对的 token”，不需要复制一套 HITL 状态机。

### 8. 增加消息投递与回调审计记录

为了对齐 PRD 中的 delivery records / debugging 诉求，需要记录：

- 哪个 form
- 哪个 recipient / contact
- 哪个通道（feishu / email）
- provider message id
- 发送状态
- 回调状态
- 失败原因

这样做的原因：

- Demo 期间最容易出问题的就是“通知到了谁”“为什么没恢复”“是不是重复提交”。
- 这些记录后续也能自然演进成 PRD 里的 delivery / resolution records。

## Risks / Trade-offs

- [Contact 只有脚本导入，没有编辑能力] → 用导入脚本和最小查询能力先满足 Demo；正式 Contact / Human Roster 管理能力留到后续 PRD 落地。
- [默认 IM + Email 会产生双份通知] → 这是 PRD 既定行为，Demo 期间通过说明与日志降低困惑。
- [当前卡片只强支持 text/select] → 对不支持字段统一降级为 IM 审批链接，不让通知链路整体失败。
- [飞书 listener 是独立进程，可能被忘记启动] → 提供明确的 CLI 入口、启动检查项和日志输出。
- [Figma PRD 当前仍未直接读取] → 本次设计以 lark-cli 读取到的 Feishu PRD、用户会话约束和本地补充文档为准；涉及 UI 细节不在本次 Demo 决策面内。

## Migration Plan

1. 增加最小 contact/contact-import 能力，并通过脚本导入当前 workspace members。
2. 增加飞书配置项和官方 SDK 依赖。
3. 增加飞书绑定入口与回调。
4. 增量扩展现有 HITL 通知链路，实现 member contact 的 `IM + Email` 发送。
5. 增加飞书长连接 listener 命令。
6. 用 Demo 账号完成绑定，验证绑定、发卡、提交、恢复执行。

回滚策略：

- 停掉飞书 listener。
- 关闭或清空飞书配置。
- 保留 contact 导入数据不影响现有 email/webapp HITL。
- 现有 HITL email/webapp 路径继续工作。

## Open Questions

- 本次 Demo 不阻塞的 open question 是：member contact 导入表是否需要从第一天就带上“external contact 兼容字段”。默认答案是“结构上预留，但行为上不启用”，避免为了未来范围扩大当前代码改动面。
