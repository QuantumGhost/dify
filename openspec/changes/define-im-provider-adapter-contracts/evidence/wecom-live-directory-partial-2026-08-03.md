# WeCom Directory Partial Real-Execution Receipt

- Provider 记录时间：`2026-08-02T21:50:32.390142Z`
- 执行环境：从 gitignored `temp/im.env` 加载的授权非生产配置
- Production 入口：一个 fresh `WeComAdapter` 的一次 `directory.read_snapshot()`
- Tracked fixture：`openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/wecom-live-directory-partial-2026-08-03.json`
- Tracked fixture SHA-256：`5de313d5a7f1835a8d5a4a6d41fb224aedf86fde92267766d860883a22826cdd`

## 可独立审计的 exact evidence

本 receipt 只证明 `directory.read_snapshot` 冷启动链中的 `GET /gettoken`。Production adapter 返回成功且包含
entries 的 tenant-bound 完整 snapshot；capture harness 只把五类当前缺失 entry 中实际触发的 token exchange 保留到
tracked partial fixture。其余三次请求属于已经闭合的 scope traversal，不作为新证据重复保留。

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

唯一保留的 exchange 是一次未携带 Authorization header 且无 request body 的 token GET。脱敏 fixture 保留两个
query key、response 字段 shape、HTTP `200` 和 Provider `errcode=0`；corporation ID、corporation secret、access token、
Provider message 与 expiry 数值均替换为 typed redaction markers。`agent/get`、explicit department `department/list` 与
explicit department `user/list` 各执行一次，只用于 production scope traversal，没有保留到本 partial fixture。

## 保守边界

本证据只允许闭合 Exact External Entry Inventory 中以下一行的 `real_execution` 和 `sanitized_fixture`：

- `WeCom | directory.read_snapshot | GET /gettoken`

本次 Provider-visible scope 没有触发以下请求，它们继续保持 `MISSING`：

- `GET /user/get [explicit-user branch]`
- `GET /tag/get [tag branch]`
- `GET /department/list [tag-department branch]`
- `GET /user/list [tag-department branch]`

因此 aggregate `WeCom | directory.read_snapshot` 的 `real_execution` 与 `sanitized_fixture` 仍按 conservative roll-up
保持 `MISSING`。Operation attribution 不跨 capability 复用：`basic_messaging.test_destination` 与
`basic_messaging.send_text` 的 `GET /gettoken` rows 也继续保持 `MISSING`。

## 脱敏与失败策略

写入 tracked fixture 前执行 fail-closed secret/PII scan，覆盖 `temp/im.env` 全部非空值、email、phone、IPv4、IPv6、
WeCom corporation ID 与 Bearer/token pattern。结果通过；fixture 不保留 credentials、PII、Provider identity 或 raw
headers。首个 HTTP/Provider failure 会在 adapter retry 分支前终止；本次没有 HTTP/Provider failure，且没有 retry。
