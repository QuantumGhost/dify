# Feishu API Phase A Partial Real-Execution Receipt

- Provider 记录时间：`2026-08-03T06:36:42.719959Z`
- 执行环境：从 gitignored `temp/im.env` 加载的授权非生产配置
- Production 入口：6 个 fresh `FeishuLarkAdapter`，分别执行 credential、Directory、destination、text send、card send 与 exact-reference card update
- Directory pagination seam：`directory_page_size=1`
- Tracked fixture：`openspec/changes/define-im-provider-adapter-contracts/evidence/fixtures/feishu-live-api-phase-a-2026-08-03.json`
- Tracked fixture SHA-256：`1b03c3cda30ff169762790fed95af5865f341442b4b49a693b2a697da2176d45`

## 可闭合的 exact evidence

以下 exact entries 均保留了对应的完整脱敏 request/response shape；每个 operation 的 cold token exchange 与其 Provider call 在同一个 fresh adapter invocation 中发生：

- `Feishu/Lark | basic_messaging.test_destination | POST /auth/v3/tenant_access_token/internal`
- `Feishu/Lark | basic_messaging.test_destination | GET /contact/v3/users/{id} [open_id]`
- `Feishu/Lark | basic_messaging.test_destination | GET /contact/v3/users/{id} [user_id]`
- `Feishu/Lark | basic_messaging.test_destination | GET /contact/v3/users/{id} [union_id]`
- `Feishu/Lark | basic_messaging.send_text | POST /auth/v3/tenant_access_token/internal`
- `Feishu/Lark | basic_messaging.send_text | POST /im/v1/messages [text]`
- `Feishu/Lark | dynamic_card.send_card | POST /auth/v3/tenant_access_token/internal`
- `Feishu/Lark | dynamic_card.send_card | POST /im/v1/messages [interactive]`
- `Feishu/Lark | dynamic_card.update_card | POST /auth/v3/tenant_access_token/internal`
- `Feishu/Lark | dynamic_card.update_card | PATCH /im/v1/messages/{message_id}`

Text、interactive card 与 exact-reference update 均得到 Provider acceptance。Fixture 使用稳定不可逆 pseudonym 证明 card-send response reference 与 update request path 指向同一条消息，不保留真实 message identifier。

## 同批次只读观察

- `credential.test_credentials` 成功；一次 cold token、一次 tenant query，并以 `page_size=1` 读取两页 contact scope。
- `directory.read_snapshot` 成功并返回 tenant-bound non-empty snapshot；同样读取两页 contact scope 与两个 explicit-user profiles。
- 当前非生产 app 的 contact scope 没有 department visibility root，因此 production adapter 未进入 department-children 或 department-users branch；这两个 exact entries 与 Directory aggregate 继续保持 `MISSING`。

上述只读 entries 已有旧 receipt/fixture 关闭。本 receipt 保留本批次重新观察到的脱敏 exchange，但不改变已关闭 cell 的证据归属。

## 保守边界

- `email`：实际发起一次 batch identity lookup，Provider 返回后由 production adapter 归类为 `destination_unreachable`；该分支继续 `MISSING`。
- Slack/Feishu Webhook、Feishu STREAM 与任何 Provider configuration 页面均未执行。
- Destination aggregate 因 `email` exact entry 未关闭而继续 `MISSING`。

## Side-effect 与脱敏审计

| Audit item | Count |
| --- | ---: |
| Fresh adapter instances | 6 |
| Top-level operation invocations | 6 |
| Text message Provider calls | 1 |
| Interactive-card Provider calls | 1 |
| Exact-reference card-update Provider calls | 1 |
| Automatic retries | 0 |
| Provider configuration changes | 0 |

Recorder 在 network I/O 前限制 Feishu HTTPS origin、method、path、pagination seam、authorization presence 与 allowed operation paths，并在内存中脱敏 response。落盘前扫描全部 env values、Bearer material、Feishu identifiers、Email、phone、IP 与 raw dynamic paths；fixture 不保留 raw headers、credentials、Provider identity 或 PII。
