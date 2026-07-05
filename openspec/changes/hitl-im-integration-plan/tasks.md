## 1. Demo Scope And Provider Readiness

- [ ] 1.1 准备飞书企业自建应用 credentials、signing/encrypt config、bot token、callback URL 和测试群/用户。
- [ ] 1.2 定义 demo transitional path：复用现有前端 HumanInput v1 编排界面，前端提交 v1 node config，后端/runtime 映射到 HumanInput v2 runtime model。
- [ ] 1.3 定义 demo 表单样例，覆盖 paragraph、select、file、file-list 和 actions；file/file-list 允许走 Web form fallback。
- [ ] 1.4 复核飞书 wiki PRD 和 Figma HITL 节点；如仍不可访问，记录缺失项并继续按当前 spec 实现。

## 2. Contact Model And Sync

- [x] 2.1 新增 `Contact` model，支持 member/external、account reference、name、email、status、source、tenant scope。
- [x] 2.2 新增 Contact repository/service，所有读写按 workspace scope 过滤。
- [x] 2.3 新增 demo/test seed script，从指定 Workspace 的现有 members 创建缺失的 member Contacts。
- [x] 2.4 明确 Contact 自动同步、lazy materialization、正式迁移/投影策略不属于 demo 范围，并保留后续设计入口。
- [x] 2.5 为 external Contact 实现最小管理能力：一个 name、一个 email、无 IM identity。
- [ ] 2.6 在 HITL form recipient / delivery / submission 中保存 Contact snapshot。
- [ ] 2.7 添加 Contact tests，覆盖 seed script 幂等创建、external contact 和 snapshot 保留。

## 3. IM App Configuration

- [x] 3.1 新增 provider、install mode、install status、token status 等 enum/domain constants。
- [x] 3.2 新增 IM app config resolver 和 `IMAppContext` value object，支持 `self_built` 和 `isv`，并预留 deployment global 与 tenant override。
- [ ] 3.3 实现 config resolver：CE deployment global；EE tenant override > deployment global；Cloud Slack ISV / DingTalk tenant self-built；deployment global 可来自 config/secret manager，不强制落 DB。
- [ ] 3.4 实现 Slack ISV install/uninstall/token refresh 数据路径和接口边界；只有需要生命周期管理的 install/config 才落 DB。
- [ ] 3.5 实现 self-built app credential 配置读取与校验，供飞书 demo 和钉钉企业自建复用。
- [ ] 3.6 添加 app config tests，覆盖版本分支、缺失 credentials、token refresh/rotation 和 uninstall。

## 4. Provider-Neutral IM Core

- [x] 4.1 新增 provider-neutral DTOs，用于 binding callback、send command、send result、submission callback 和 card update command。
- [x] 4.2 定义 `HumanInputIMProvider` protocol，覆盖 signature verification、form send、submission parse、message update 和 challenge response。
- [x] 4.3 新增 provider registry，通过 app config resolver 获取 provider credentials。
- [x] 4.4 新增 provider-neutral service，协调 binding lookup、delivery send、callback idempotency、card update compensation 和 form submission。
- [ ] 4.5 为 provider-neutral service 添加单元测试，覆盖 provider missing、signature failure、binding mismatch、duplicate event 和 card update retry。

## 5. Contact IM Binding

- [x] 5.1 新增 IM binding model，绑定 `account_id`、credential scope 与 provider identity，不强制依赖统一 `app_installation_id` 外键。
- [x] 5.2 实现 binding repository，普通唯一键保护同一 credential scope + provider workspace user 不重复绑定。
- [x] 5.3 在 service 层事务校验第一期每个 member Contact/Account 只有一种 active IM。
- [x] 5.4 实现创建 time-limited binding session 的 service。
- [x] 5.5 实现 provider-authenticated binding callback，完成 Account 与 IM identity 的 active binding。
- [x] 5.6 实现 binding inspect/revoke API，用于当前 account 查看和撤销绑定。
- [x] 5.7 添加 binding tests，覆盖重复绑定、多 provider 预留、过期 session、revoke 后不可投递和 MySQL-compatible 约束。

## 6. New HITL Runtime And Delivery

- [x] 6.1 新增新 HITL `NodeType`、新 `Version` 和 Contact recipient schema。
- [x] 6.2 新增 `Allow Current Initiator to Approve` 配置与 actor 解析：Console/CLI OpenAPI 为 Account，Web App/Service API 为 EndUser。
- [x] 6.3 实现 demo compatibility mapping，将前端提交的 HumanInput v1 node config 映射为 HumanInput v2 runtime model，覆盖 form content、inputs、actions、timeout 和 member recipients。
- [x] 6.4 在 runtime 创建 Human Input form recipient 时保存 Contact snapshot 和 initiator approval snapshot。
- [x] 6.5 新增 `dispatch_human_input_im_task`，按 form id 加载 form、recipient snapshot、binding、resolver 返回的 app context 和 variable pool。
- [x] 6.6 实现 member Contact 投递：有 IM binding 发 IM，无 IM binding fallback email，无 email skip 并写入 `process_data`。
- [x] 6.7 实现 external Contact 投递：只发 email。
- [x] 6.8 实现 provider adapter 的 form/card rendering，支持 paragraph、select、actions，并为 file/file-list 加 Web form fallback。
- [x] 6.9 持久化 IM message correlation，记录 send success/failure、provider message id 和 target card status。
- [x] 6.10 持久化 interaction mapping snapshot，记录 provider input component id 到 Dify `output_variable_name`、provider action id 到 Dify `user_actions[].id` 的映射。
- [x] 6.11 添加 runtime/delivery tests，覆盖 v1 frontend-submitted config 走 v2 runtime、bound recipient、missing binding email fallback、skip、external contact、initiator approval、provider send failure、interaction mapping snapshot 和 retry idempotency。

## 7. Feishu Self-Built Demo Adapter

- [x] 7.1 实现飞书自建应用 signature/challenge verification。
- [x] 7.2 实现飞书 message/card 发送 API 调用与错误映射。
- [x] 7.3 实现飞书 interactive form callback parser，输出 provider-local component/action id，不直接输出 Dify field/action id。
- [x] 7.4 实现飞书 submitted/error card update。
- [x] 7.5 添加飞书 adapter contract tests，使用 fixture payload 覆盖 valid callback、invalid signature、malformed payload、unknown component、challenge 和 duplicate event。

## 8. IM Callback And Workflow Resume

- [x] 8.1 新增外部 webhook controller，例如 `api/controllers/trigger/human_input_im.py`。
- [x] 8.2 在 callback service 中验证 provider event id 幂等，重复事件返回成功 ACK。
- [x] 8.3 校验 callback provider user 与 active binding、Contact snapshot、original recipient、provider workspace 一致。
- [x] 8.4 使用 interaction mapping snapshot 将 provider submission 映射为 `HumanInputService.submit_form_by_token` 参数，并按 actor 类型写入 `submission_user_id` 或 `submission_end_user_id`。
- [x] 8.5 加固 `HumanInputFormSubmissionRepository.mark_submitted` 的单次提交语义，避免并发 callback 重复 resume。
- [x] 8.6 更新 IM message status，记录 submitted、validation error、expired、already handled 等状态。
- [x] 8.7 实现 card update 异步补偿任务，callback 成功后不阻塞 workflow resume。
- [x] 8.8 添加 callback/resume tests，覆盖 active form、expired form、already submitted form、binding mismatch、unknown component/action id、initiator approval 和 resume enqueue once。

## 9. Frontend And Configuration

- [ ] 9.1 Demo 前复用现有前端 HumanInput v1 编排界面，最多做极少非结构性调整；正式 Contact-based HITL node 配置 UI、Contact 管理 UI 和 IM binding/config UI 不属于 demo 范围。
- [ ] 9.2 后续在 Web 侧新增 Contact 管理和 Contact recipient 配置入口，使用现有 i18n 规范添加文案。
- [ ] 9.3 展示当前 account 的 IM binding status，并支持 revoke。
- [ ] 9.4 增加 IM app config/install UI，包括 Cloud Slack ISV install 和 self-built credential 配置。
- [ ] 9.5 对未绑定 IM 的 member Contact 展示 email fallback 状态，而不是静默失败。

## 10. Observability And Operations

- [ ] 10.1 为 Contact seed、binding、delivery、callback、card compensation 和 resume enqueue 增加结构化日志。
- [ ] 10.2 在 logs/status 中包含 tenant、app、workflow run/conversation、form、contact snapshot、provider、message 和 event identifiers。
- [ ] 10.3 增加 provider config 校验，启动或首次调用时能发现缺失 credentials。
- [ ] 10.4 定义 operator 排障路径，包含 Contact missing、delivery fallback/skip、callback rejected、form expired、card update failed 和 resume enqueue failed。
- [ ] 10.5 确认 rollback 行为：关闭新 HITL/IM provider config 后不影响旧 HITL、Web/Email submission 和现有 workflow resume。

## 11. Verification

- [ ] 11.1 运行 backend targeted unit tests，覆盖新增 Contact、app config、binding、provider adapter、delivery、callback 和 controller。
- [ ] 11.2 运行现有 Human Input 相关 unit tests，确认旧 HITL 没有回归。
- [ ] 11.3 手工跑通飞书 demo：绑定账号、触发 HITL pause、飞书收到表单、飞书内提交、Dify workflow 继续执行。
- [ ] 11.4 手工验证 IM 未绑定时 fallback email，email 缺失时 skip 并写入 `process_data`。
- [ ] 11.5 手工验证 first valid submission wins 和卡片状态异步补偿。
- [ ] 11.6 记录 demo 后补齐项，包括正式新 NodeType 前端、v1-to-v2 compatibility mapping 收敛计划、旧 HITL opt-in migration、更多 provider 和 EE 跨 Workspace Contact 决策。
