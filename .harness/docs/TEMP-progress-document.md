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
