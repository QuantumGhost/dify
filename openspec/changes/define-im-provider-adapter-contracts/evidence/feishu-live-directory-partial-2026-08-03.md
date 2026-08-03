# Feishu Directory Partial Real-Execution Receipt

- Provider 记录时间：`2026-08-02T21:22:40.269705Z`
- 执行环境：从 gitignored `temp/im.env` 加载的授权非生产配置
- Production 入口：一个 fresh `FeishuLarkAdapter` 的一次 `directory.read_snapshot()`
- Source attempt SHA-256：`b003b70793a1b4d3d428e9556f8ff7f9ecdf63b2e384c149bb335db0e969bfca`
- Tracked fixture：`openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/feishu-live-directory-partial-2026-08-03.json`
- Tracked fixture SHA-256：`65d80ae2c1d22797065cea99b6b1644a59dae60b9b514075819388d2695e11f7`

## 可独立审计的 exact evidence

本 receipt 只证明 `directory.read_snapshot` 冷启动链中的
`POST /auth/v3/tenant_access_token/internal`。Production adapter 返回成功的完整可见范围 snapshot 后，capture
harness 在检查三类待补 exchange 时发现当前 Provider scope 没有 department roots，因此拒绝生成完整 Directory
fixture。后续提升步骤没有再次调用 Provider；它仅把原 gitignored attempt 中已经脱敏并通过扫描的 token exchange
复制到 tracked partial fixture。

该 exact row 的 operation attribution 由同一次 attempt 的以下计数共同约束：

| Audit item | Count |
| --- | ---: |
| Fresh adapter instances | 1 |
| `directory.read_snapshot` invocations | 1 |
| `credential.test_credentials` invocations | 0 |
| Automatic retries | 0 |
| Messaging invocations | 0 |
| GUI invocations | 0 |
| Provider configuration changes | 0 |

唯一保留的 exchange 是一次未携带 Authorization header 的 token POST。脱敏 fixture 保留 request/response 字段
shape、HTTP `200` 和 Provider `code=0`；app ID、app secret、tenant token、Provider message 与 expiry 数值均替换为
typed redaction markers。Tenant query、contact scopes 与两次 explicit-user exchange 只用于 production scope traversal，
没有重新保留到本 partial fixture。

## 保守边界

本证据只允许闭合 Exact External Entry Inventory 中以下一行的 `real_execution` 和 `sanitized_fixture`：

- `Feishu/Lark | directory.read_snapshot | POST /auth/v3/tenant_access_token/internal`

本次 Provider-visible scope 没有触发以下请求，它们继续保持 `MISSING`：

- `GET /contact/v3/departments/{department_id}/children [paginated]`
- `GET /contact/v3/users/find_by_department [paginated]`

因此 aggregate `Feishu/Lark | directory.read_snapshot` 的 `real_execution` 与 `sanitized_fixture` 仍按 conservative
roll-up 保持 `MISSING`。本 receipt 不证明 department traversal，也不把 preclosed exchange 重复计作新证据。

## 脱敏与失败策略

写入 attempt 和 tracked fixture 前均执行 fail-closed secret/PII scan，覆盖 `temp/im.env` 全部非空值、email、phone、
IPv4、IPv6、Bearer/token pattern、raw Feishu ID 与动态 path ID。结果通过；fixture 不保留 credentials、PII、
Provider identity 或 raw headers。首个 HTTP/Provider failure 会在 adapter retry 分支前终止；本次没有 HTTP/Provider
failure，且没有 retry。
