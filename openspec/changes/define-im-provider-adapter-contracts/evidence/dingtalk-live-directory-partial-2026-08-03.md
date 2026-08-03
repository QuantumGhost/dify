# DingTalk Directory Token Real-Execution Receipt

- Provider 记录时间：`2026-08-02T22:08:54.469703Z`
- 执行环境：从 gitignored `temp/im.env` 加载的授权非生产配置
- Production 入口：一个 fresh `DingTalkAdapter` 的一次 `directory.read_snapshot()`
- Tracked fixture：`openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/dingtalk-live-directory-partial-2026-08-03.json`
- Tracked fixture SHA-256：`582faf390c52e8bb4761fe015100ca0ba270167e64b7a1d50cba1c287ef62c80`

## 可独立审计的 exact evidence

本 receipt 只新增证明 `directory.read_snapshot` 冷启动链中的 corp-bound
`POST /v1.0/oauth2/{corpId}/token`。Production adapter 返回成功且包含 entries 的 tenant-bound 完整 snapshot；capture
harness 只保留当前缺失的 token exchange。其余四次请求属于已经闭合的 permission probe 与 Directory traversal，
不作为新证据重复保留。

该 exact row 的 operation attribution 由同一次运行的以下计数共同约束：

| Audit item | Count |
| --- | ---: |
| Fresh adapter instances | 1 |
| `directory.read_snapshot` invocations | 1 |
| `credential.test_credentials` invocations | 0 |
| `basic_messaging.test_destination` invocations | 0 |
| `basic_messaging.send_text` invocations | 0 |
| Automatic retries | 0 |
| Provider configuration changes | 0 |

唯一保留的 exchange 是一次未携带 Authorization header 且无 query 的 token POST。脱敏 fixture 保留 redacted
corporation path segment、request/response 字段 shape 与 HTTP `200`；client ID、client secret、grant、access token 与
expiry 数值均替换为 typed redaction markers。

同一次 Directory operation 还各执行一次 department permission probe、user permission probe、department hierarchy
traversal 与 user traversal。这四类请求已由
`openspec/changes/define-im-provider-adapter-contracts/evidence/dingtalk-live-read-only-2026-08-02.md` 和对应 fixture
闭合，因此本 fixture 只记录 observed count，不保留其 exchange。

## 保守边界

本证据只新增闭合 Exact External Entry Inventory 中以下一行的 `real_execution` 和 `sanitized_fixture`：

- `DingTalk | directory.read_snapshot | POST /v1.0/oauth2/{corpId}/token`

该 operation 的其他四个 exact rows 已有独立 evidence；token row 闭合后，aggregate
`DingTalk | directory.read_snapshot` 的 `real_execution` 与 `sanitized_fixture` 可按 conservative roll-up 闭合。

以下四个 DingTalk exact gaps 与本次 operation attribution 无关，继续保持 `MISSING`：

- `basic_messaging.test_destination` 的 token POST 与 personal-user lookup；
- `basic_messaging.send_text` 的 token POST 与 one-to-one robot send。

本次未准备或执行 Messaging。

## 脱敏与失败策略

写入 tracked fixture 前执行 fail-closed secret/PII scan，覆盖 `temp/im.env` 全部非空值、email、phone、IPv4、IPv6、
DingTalk identity、UUID 与 Bearer/token pattern。结果通过；fixture 不保留 credentials、PII、Provider identity 或 raw
headers。首个 HTTP non-2xx 或 legacy nonzero `errcode` 会在 adapter Directory retry 判断前终止；本次没有
HTTP/Provider failure，且没有 retry。
