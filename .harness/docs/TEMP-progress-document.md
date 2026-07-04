# HITL IM Planning Progress

## 2026-07-02

### 当前状态

- Status: planning complete
- Implementation: not started
- Blocker level: partial

### 已完成

1. 阅读并采纳 `Squad Development Requirements`。
2. 确认仓库当前不存在 `.harness`，已补建临时规划文档用于后续迭代承接。
3. 阅读飞书 PRD：
   - `https://langgenius.feishu.cn/wiki/GMFdwe40Oi2rC9klP2HcNjnHnwd`
4. 阅读并梳理现有代码边界：
   - `api/services/human_input_service.py`
   - `api/core/repositories/human_input_repository.py`
   - `api/core/workflow/human_input_adapter.py`
   - `api/core/workflow/human_input_policy.py`
   - `api/core/workflow/human_input_forms.py`
   - `api/controllers/console/human_input_form.py`
   - `api/controllers/service_api/app/human_input_form.py`
   - `api/controllers/openapi/human_input_form.py`
   - `api/tasks/mail_human_input_delivery_task.py`
   - `web/app/components/workflow/nodes/human-input/...`
5. 确认当前 external delivery 语义已经存在，但只真实落地到 Email。
6. 与用户确认首个 IM provider 选择为 `Feishu/Lark`。
7. 补充核对飞书卡片能力边界，并把“card-first，超出能力才降级链接”加入计划约束。
8. 与用户确认 `file / file-list` 不要求卡片内支持。
9. 与用户确认 demo 阶段允许用 environment variable 提供 Feishu credentials，但正式目标需要 tenant-level provider config。
10. 确认 demo 可使用 `/Users/qg/workspace/langgenius/im-integration/feishu.env`，并验证存在：
   - `LARK_APP_ID`
   - `LARK_APP_SECRET`
   - `LARK_EVENT_MODE`
11. 记录用户新增约束：provider inbound path 需要抽象 `webhook` 与 `polling` 两类接入模式。
12. 记录用户新增约束：飞书回调 E2E 难以完全自动化，必须强化 fixture / contract / simulation 测试链路。
13. 记录用户新增约束：IM provider 接入必须优先使用官方 SDK。
14. 将 ingress 建议从 `webhook-first` 调整为 `non-webhook-first`，对 Feishu 首实现具体落在官方 SDK 的 `long connection` 模式。
15. 根据官方资料，将 SDK 选择进一步收敛为：
   - `lark-oapi` for OpenAPI
   - `lark-channel-sdk` for long connection / channel ingress

### 关键发现

- 当前 HITL 已有足够稳定的 `form -> submit -> resume` 主链路，IM 不需要另造 resume 机制。
- 当前数据模型已经有 `form / delivery / recipient` 三层，适合继续扩展，不适合重写。
- 前端 Slack 入口已占位，但后端没有对应 delivery type 与 provider。
- 本期最大新增不是“表单本身”，而是：
  - provider config
  - account binding
  - callback verification
  - provider delivery records
- 还需要新增一层“interaction capability abstraction”，否则后续接 Slack / Teams 时会把 provider 差异泄漏到业务层。
- 当前 Web 端 `paragraph` 字段是 `Textarea` 语义，不能把所有文本字段都默认视为 Feishu 卡片单行 `input`。
- `file / file-list` 已经可以从计划里直接排除出 inline card 能力范围。
- provider config 不能直接绑死在 `dify_config` 上，至少要先抽出 config store 接口。
- 用户已明确要求 `paragraph` 必须进入首切，但需要区分“可渲染到卡片”与“可在卡片内获得等价 multiline 输入体验”。
- provider inbound path 还需要再抽一层 ingress adapter，否则 webhook/polling 的差异会污染 controller 和业务服务。
- `LARK_EVENT_MODE` 已经出现在 demo 配置里，说明接入模式切换值得在首轮设计时就抽象出来。
- 对 Feishu 来说，真正适合首实现的“非 webhook”路径，不应是我们自己轮询消息列表，而应优先落官方 SDK 的长连接接入。
- 当前仓库 backend 依赖里还没有飞书官方 SDK，需要在实现阶段新增依赖。

### 未解决项

- Figma PRD 无法通过当前接入身份读取，设计细节未直接核验。
- 飞书卡片对多行文本、复杂字段、文件输入的最终支持边界，还需要在实现前按官方组件清单再做一次字段映射确认。
- tenant-level provider config 的持久化模型和管理入口本轮还没细化到字段级。
- 如果未来要做真正的 polling path，仍需确认其是否能完整覆盖卡片交互回流，而不是只能做消息读取。

### 推荐的下一个动作

1. 冻结下周一前的字段子集：
   - recipient 范围
   - form input 类型范围
   - card/modal 交互形态
2. 先实现 provider-neutral form model + capability profile。
3. 同步实现 provider config store 接口，首版落 env-backed。
4. 同步实现 provider ingress adapter 抽象，Feishu 首版优先 official SDK long-connection concrete path。
5. 先做 backend vertical slice，再补 frontend binding / node config。
6. 只有在 inline card 判定失败时才走 link fallback。

### 验证说明

- 本轮是规划，不涉及代码实现。
- 验证方式为 PRD 阅读、官方文档阅读、代码阅读、测试夹具与现有 E2E 语义核对。
- 未运行仓库测试命令。

### 工具环境备注

- `lark-cli` 可正常读取飞书文档。
- 当前 `lark-cli` 版本为 `1.0.59`，有可用更新 `1.0.63`。
- Figma 文件当前因权限原因无法直接读取。

## 2026-07-03

### 当前状态

- Status: implementation complete for demo scope
- Implementation: backend + frontend demo slice complete
- Blocker level: low

### 已完成

1. 为 HITL delivery adapter 增加通用 `IM` delivery type。
2. 增加 IM recipient payload 与 `ApprovalChannel.IM`。
3. 增加 env-backed provider config store：
   - provider
   - ingress mode
   - app id / app secret
   - optional verification token / encrypt key
4. 增加账户域 IM binding model 与 binding service。
5. 在 HITL repository 中接入 IM recipient materialization。
6. 增加 provider-neutral IM notification entities。
7. 增加 Feishu card builder，支持：
   - markdown content
   - `paragraph` -> `input(multiline_text)`
   - `select` -> `select_static`
   - `file/file-list` -> link fallback
8. 增加 IM delivery task 与 dispatcher。
9. 在 workflow pause notification enqueue 中接入 IM task。
10. 增加 IM callback translator：
    - token -> recipient lookup
    - operator identity match
    - submit to existing `HumanInputService.submit_form_by_token(...)`
11. 增加 Feishu webhook ingress service。
12. 增加 Feishu long-connection service。
13. 增加 trigger callback controller：
    - `/triggers/human-input/im/feishu/callback`
14. 增加 current-account manual binding API：
    - `GET /account/im-bindings`
    - `PUT /account/im-bindings/<provider>`
15. 将官方 SDK 依赖写入 `api/pyproject.toml`：
    - `lark-oapi`
    - `lark-channel-sdk`
16. 将 IM recipient payload 从 provider-specific snapshot 收敛为稳定的：
    - `account_id`
    - `binding_id`
17. 增加 core-level binding repository，并让 HITL repository 依赖 core repository，而不是 service 层。
18. 为 IM binding 写路径增加显式 commit、冲突翻译与 `409` 语义。
19. 为 env-backed config 增加可选 `tenant_id` owner。
20. 将 webhook / ws callback 中的业务拒绝从 generic 500 收敛为成功 ack + 本地拒绝处理。
21. 删除 `polling` 配置值，只保留：
    - `webhook`
    - `stream`
22. 为 long-connection startup wiring 增加 extension 级测试。
23. 增加“绑定专用”的 Feishu OAuth flow：
    - 当前已登录 Dify 账号发起绑定
    - OAuth callback 仅创建或刷新 `AccountIMBinding`
    - 明确不接入飞书登录
24. 增加账户页最小 Feishu 绑定设置：
    - 手工填写 `open_id / user_id`
    - Feishu OAuth 显式绑定按钮
    - OAuth 回调后刷新当前绑定状态
25. 为账户页绑定能力补充前端测试与多语言文案。

### 已验证

- 聚合后端单测：
  - `73 passed`
- 后端静态检查：
  - `uv run --project api ruff check ...`
- 前端定向测试：
  - `pnpm -C web test 'app/account/(commonLayout)/account-page/__tests__/feishu-binding-card.spec.tsx'`
- 前端定向 lint：
  - `pnpm -C web exec eslint 'app/account/(commonLayout)/account-page/feishu-binding-card.tsx' 'app/account/(commonLayout)/account-page/client.ts' 'app/account/(commonLayout)/account-page/__tests__/feishu-binding-card.spec.tsx'`
- locale lint：
  - `pnpm -C web exec eslint 'i18n/*/common.json'`
- 核对了官方 SDK 与文档：
  - `lark-oapi`
  - `lark-channel-sdk`
  - Feishu card markdown / input / select / callback docs

### 仍未完成

1. tenant-scoped provider config 仍只有抽象，没有持久化实现。
2. reviewer subagent 流程本轮未执行；若后续继续大改，需要让所有 subagent 先读取 `Squad Development Requirements`。
3. 还没有把飞书 app 凭据从 env-backed 方案迁移到租户级配置界面。

### 已知风险

- 当前 demo env 的 `LARK_EVENT_MODE=webhook`，实际演示若不改配置，将走 webhook ingress，不会默认走 stream。
- `FeishuLongConnectionService` 目前已具备 service 级实现，但尚未挂到独立进程/命令入口。
- `polling` 已从配置面删除，不再作为可选运行模式暴露。
- 现有 self-binding API 足够 demo，但若要支持 workspace 内多人通知，需要再补成员级 binding 管理面。
- 当前前端账户页只提供最小 binding surface，没有 provider config 管理页。

## 2026-07-03 Mergeability Check

### 当前状态

- Status: merged and stabilized
- Merge target health:
  - `upstream/main`: clean after rebasing expectation update
  - `upstream/feat/hitl-file-in-body`: clean
  - `upstream/feat/agent-hitl-ask-human`: conflict-heavy

### 已完成

1. `fetch` 并复核了当前可见的上游 HITL 相关远端分支。
2. 首次检查时确认当前分支 `feat/hitl-im` 与旧的 `upstream/main` merge-base 是 `51156fef07`。
3. 在用户提醒后重新 `fetch upstream main`，确认 `upstream/main` 已前进到 `c080e2c3b8`，当前分支相对它是：
   - ahead `4`
   - behind `35`
4. 在临时 worktree 中做了四次非破坏性合并演练：
   - `latest upstream/main(c080e2c3b8) <- feat/hitl-im`
   - `upstream/main <- feat/hitl-im`
   - `upstream/feat/hitl-file-in-body <- feat/hitl-im`
   - `upstream/feat/agent-hitl-ask-human <- feat/hitl-im`
5. 读取了本地未跟踪的 `api/core/workflow/nodes/human_input/` 重构目录，确认它仍然复用了：
   - `core.workflow.human_input_adapter.DeliveryChannelConfig`
   - 现有 Human Input 事件/模型语义

### 关键发现

- 当前分支合并到最新的 `upstream/main(c080e2c3b8)` 仍然是干净的，没有文本冲突。
- 这意味着当前分支虽然落后 `upstream/main` 35 个提交，但从合并成本上看仍然属于“容易合并”。
- 在当前工作树里执行真实 `git merge upstream/main` 时，最初被本地未跟踪文件阻塞：
  - `api/core/workflow/nodes/human_input/__init__.py`
  - `api/core/workflow/nodes/human_input/_exc.py`
  - `api/core/workflow/nodes/human_input/entities.py`
  - `api/core/workflow/nodes/human_input/enums.py`
- 这些未跟踪文件会被 `upstream/main` 上已跟踪的同路径文件覆盖，所以 Git 按预期中止了首次合并尝试。
- 随后已将这 4 个本地文件安全备份到：
  - `/tmp/dify-human-input-backup-20260703-132019`
- 在保留本地独有的 `form_processing.py`、`hitl.py`、`node.py` 前提下，`upstream/main` 已成功真实合并到当前分支，merge commit 为：
  - `d402febffb`
- 当前分支合并到 `upstream/feat/hitl-file-in-body` 也是干净的，没有文本冲突。
- 当前分支合并到 `upstream/feat/agent-hitl-ask-human` 会产生多处冲突，但主要集中在：
  - agent app runtime / request builder
  - `agent_v2/ask_human_hitl.py`
  - `resume_agent_app_task.py`
  - `api/models/human_input.py`
  - `api/core/repositories/human_input_repository.py`
- 这些冲突大多不是 IM delivery 本身引起的，而是因为 `feat/agent-hitl-ask-human` 建立在较老的基线上，同时又深改了 ask-human 的暂停 / 恢复链路。
- 本地未跟踪的 `api/core/workflow/nodes/human_input/` 重构并没有绕开 `human_input_adapter`，这说明我们在 `DeliveryChannelConfig` / `ApprovalChannel.IM` 上的扩展仍然有较高概率能复用到那套结构。

### 验证说明

- 已完成真实 merge，并修复 merge 后暴露出的两处兼容问题：
  - `api/tasks/human_input_im_delivery_task.py` 改为依赖 Dify-owned HITL entities，而不是旧的 `graphon.nodes.human_input.entities`
  - `api/tests/unit_tests/core/app/apps/test_workflow_app_runner_notifications.py` 对齐新的 pause reason / enrich 流程
- 同时修复了 reviewer 指出的两项高优先级实现问题：
  - Feishu OAuth link token 仅在绑定成功后撤销
  - IM dispatcher channel cache key 纳入完整 provider config
- 并补了输入边界收口：
  - 手工绑定 API / service 对 `open_id`、`user_id` 做 `strip + 非空` 规范化
- 使用的验证方式：
  - `git fetch` / 远端分支检查
  - `git rev-list --left-right --count`
  - 临时 `git worktree` + `git merge --no-commit --no-ff`
  - 读取本地未跟踪的 HITL node 重构目录
  - `uv run --project api pytest ...`（定向 121 项）
  - `uv run --project api pytest ...`（针对 P1 / 边界修复的 46 项）
  - `uv run --project api ruff check ...`
  - `pnpm -C web test 'app/account/(commonLayout)/account-page/__tests__/feishu-binding-card.spec.tsx'`
  - `pnpm -C web exec eslint 'app/account/(commonLayout)/account-page/feishu-binding-card.tsx' 'app/account/(commonLayout)/account-page/client.ts' 'app/account/(commonLayout)/account-page/__tests__/feishu-binding-card.spec.tsx'`

### 建议

1. 当前分支已经可以继续以 `upstream/main` 为基线开发。
2. 需要尽快处理 architecture reviewer 标出的两项边界问题：
   - `core.repositories.human_input_repository` 中硬编码 `provider="feishu"`
   - dispatcher 同时承担 outbound sender 与 ingress transport 选择
3. 如果未来要叠到 `upstream/feat/agent-hitl-ask-human`，仍建议先把 IM 相关逻辑从当前 `human_input_repository` / `models.human_input` 的具体字段耦合中再收紧一层，否则后续 ask-human / agent-v2 继续演进时还会反复碰撞。

## 2026-07-03 Untracked Code Convergence

### 当前状态

- Status: assessed
- Scope: current untracked code only

### 已完成

1. 盘点了当前所有未跟踪代码相关路径。
2. 对未跟踪 `api/core/workflow/nodes/human_input/*` 做了外部引用扫描。
3. 对 `create_user_tenant` helper 链条做了关联扫描。
4. 对 `api/test_isinstance.py`、`api/controllers/web/hitl-service-api-file.sh`、`openspec/config.yaml` 做了用途判断。

### 关键发现

- 当前未跟踪代码中，最需要收敛的是这两组：
  1. `api/core/workflow/nodes/human_input/form_processing.py`
  2. `api/core/workflow/nodes/human_input/hitl.py`
  3. `api/core/workflow/nodes/human_input/node.py`
  4. `api/dev/create_user_tenant.py`
  5. `dev/create-user-tenant`
  6. `api/tests/unit_tests/dev/test_create_user_tenant.py`
- `api/core/workflow/nodes/human_input/form_processing.py` / `hitl.py` / `node.py`
  - 这三份文件当前没有任何外部引用。
  - `node.py` 只自引用 `form_processing.py` 与 `hitl.py`。
  - 它们属于“未接线的 Dify-owned HITL runtime 草稿”，与当前已跟踪的：
    - `api/core/workflow/nodes/human_input/callback.py`
    - `api/core/workflow/nodes/human_input/boundary.py`
    - `graphon.nodes.human_input.human_input_node`
    在职责上存在明显重叠。
  - 它们不是当前 Feishu IM 功能运行依赖。
- `api/dev/create_user_tenant.py` / `dev/create-user-tenant` / `api/tests/unit_tests/dev/test_create_user_tenant.py`
  - 这三项是同一条完整 slice，不是无主草稿。
  - shell wrapper 调用 Python helper，单测也显式覆盖该 helper。
  - 它们当前确实“被彼此使用”，只是还没有正式纳入仓库追踪。
- `api/test_isinstance.py`
  - 是一次协议 / benchmark 实验文件。
  - 当前真实代码使用的是 `graphon.nodes.llm.runtime_protocols.LLMPollingCapableProtocol`。
  - 这份文件没有被任何生产代码或测试入口引用。
- `api/controllers/web/hitl-service-api-file.sh`
  - 是手工 curl 调试脚本，没有代码引用。
  - 它与当前 repo 中已有的 HITL 设计/实现文档一起看，更像一次性联调残留。
- `openspec/config.yaml`
  - 是工具配置，不参与运行时。
  - 当前只看到这一个孤立配置文件，没有成体系的 openspec 变更在继续推进。

### 收敛建议

1. 立即删除或移出主仓的“未接线 runtime 草稿”：
   - `api/core/workflow/nodes/human_input/form_processing.py`
   - `api/core/workflow/nodes/human_input/hitl.py`
   - `api/core/workflow/nodes/human_input/node.py`
   原因：
   - 当前无外部引用
   - 与已跟踪 runtime/boundary 职责重叠
   - 继续留在正式模块路径下，只会制造“看起来存在第二套实现”的错觉
2. `create_user_tenant` helper 链条二选一，但必须整体处理：
   - 保留方案：把 `api/dev/create_user_tenant.py`、`dev/create-user-tenant`、`api/tests/unit_tests/dev/test_create_user_tenant.py` 一起纳入版本控制，明确它是受支持的本地运维/dev helper。
   - 删除方案：三者一起删除，不要只留 shell wrapper 或只留测试。
   推荐：保留，因为它已经有测试、边界清晰、且不侵入主运行时。
3. 立即删除明显的一次性实验/联调残留：
   - `api/test_isinstance.py`
   - `api/controllers/web/hitl-service-api-file.sh`
4. `openspec/config.yaml` 单独决策：
   - 如果后续不走 openspec 工作流，直接删除。
   - 如果要继续走，就必须补齐成体系的 openspec artifacts，而不是只留一个孤立 config。

### 建议的执行顺序

1. 先删：
   - `api/test_isinstance.py`
   - `api/controllers/web/hitl-service-api-file.sh`
2. 再处理 `api/core/workflow/nodes/human_input/{form_processing.py,hitl.py,node.py}`：
   - 默认从主工作树移除
   - 如需保留草稿，转移到单独 worktree / patch / 设计目录，不再占用正式 runtime 包路径
3. 最后对 `create_user_tenant` helper 做“保留并正式纳入”或“整组删除”的明确决定。
