# Microsoft Teams Directory Graph Token Real-Execution Receipt

- Provider 记录时间：`2026-08-02T22:31:20.346227Z`
- 执行环境：从 gitignored `temp/im.env` 加载的授权非生产 Microsoft Graph 配置
- Production 入口：一个 fresh `MicrosoftTeamsAdapter` 的一次 `directory.read_snapshot()`
- Tracked fixture：`openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/microsoft-teams-live-directory-partial-2026-08-03.json`
- Tracked fixture SHA-256：`8247e09ad3dea6786d8b7215dcc4f7355dc12bdf326642dd4597bfa9cfb40701`

## 可独立审计的 exact evidence

本 receipt 只新增证明 `directory.read_snapshot` 冷启动链中的 Graph-scope
`POST /{tenant_id}/oauth2/v2.0/token`。Production adapter 返回 tenant-bound 完整 snapshot，且 snapshot 包含 entries；capture
harness 只保留该 operation 当前缺失的 token exchange。

Snapshot 与 evidence 的 completeness 独立：本次 `snapshot_outcome` 是 `success`，但由于条件性 nextLink exact row
没有被观察，`evidence_outcome` 是 `partial`。

该 exact row 的 operation attribution 由同一次运行的以下计数共同约束：

| Audit item | Count |
| --- | ---: |
| Fresh adapter instances | 1 |
| `directory.read_snapshot` invocations | 1 |
| `credential.test_credentials` invocations | 0 |
| Messaging invocations | 0 |
| Card invocations | 0 |
| Webhook invocations | 0 |
| Automatic retries | 0 |
| Provider configuration changes | 0 |

唯一保留的 exchange 是一次未携带 Authorization header 且无 query 的 Graph-scope token POST。脱敏 fixture 保留
redacted tenant path segment、request/response 字段 shape 与 HTTP `200`；client ID、client secret、grant、scope、access
token、token type 与 expiry 数值均替换为 typed redaction markers。

同一次 Directory operation 还执行一次 initial `GET /v1.0/users`。该 initial page 已由
`openspec/changes/define-im-provider-adapter-contracts/evidence/microsoft-teams-live-read-only-2026-08-02.md` 和对应 fixture
闭合，因此本 fixture 只记录 observed count，不保留其 exchange。

## 保守边界

本证据只新增闭合 Exact External Entry Inventory 中以下一行的 `real_execution` 和 `sanitized_fixture`：

- `Microsoft Teams | directory.read_snapshot | POST /{tenant_id}/oauth2/v2.0/token [Graph scope]`

initial users response 没有广告 `@odata.nextLink`，因此没有 subsequent page request；
`GET trusted @odata.nextLink [subsequent page]` 继续保持 `MISSING`。由于该 exact row 尚未闭合，aggregate
`Microsoft Teams | directory.read_snapshot` 的 `real_execution` 与 `sanitized_fixture` 必须按 conservative roll-up
继续保持 `MISSING`。

既有 live receipt 已证明 Graph token 缺少 `Organization.Read.All`；本次没有重复调用
`credential.test_credentials` 或 organization API。没有 installed bot、conversation context、trusted Bot service origin 或
authenticated Webhook Activity，因此 credential organization、八个 Messaging/Card 与四个 Webhook exact gaps 均不受影响。

## 脱敏与失败策略

写入 tracked fixture 前执行 fail-closed secret/PII scan，覆盖 `temp/im.env` 全部非空值、email、phone、IPv4、IPv6、
UUID 与 Bearer/token pattern。结果通过；fixture 不保留 credentials、tenant/client/user identity、PII、raw headers 或
initial users response。首个 HTTP non-2xx、非法 nextLink 或脱敏失败会在 production Directory retry 前终止；本次没有
HTTP/Provider/scan failure，且没有 retry。
