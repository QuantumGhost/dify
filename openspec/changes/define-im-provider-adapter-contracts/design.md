## Context

Dify 需要通过 Slack、Feishu/Lark、DingTalk、WeCom 与 Microsoft Teams 提供 credential testing、目录读取和消息发送，并通过 Slack、Feishu/Lark 与 Microsoft Teams 接入入站事件。各 Provider 的 credentials、SDK、token cache、HTTP client、directory topology、message locator 与适用的 ACK wire protocol 都不同，但这些差异不应迫使每个 capability consumer 重复构造 Provider SDK 或理解 Provider-specific lifecycle。

本设计中的根对象不是 DDD aggregate root：它不拥有业务实体或持久化一致性边界。它是 infrastructure-level facade/composite，负责把一份 immutable Provider-specific configuration 适配成一组稳定 capability views，因此命名为 `IMProviderAdapter`。

Webhook 与 STREAM 具有不同的控制流。Webhook request 先进入 Dify HTTP boundary，再调用 Provider adapter；STREAM 则由长生命周期 Provider SDK connection loop 主动回调 adapter。两者不能被压成一个假的 receive interface，但可以在完成 transport authentication 后通过同一个 `AuthenticatedIMEvent` 和 application-supplied `IMEventSink` 汇合。

## Goals / Non-Goals

**Goals:**

- 一份 Provider configuration 只构造一个 `IMProviderAdapter`，由 adapter 统一拥有 SDK client bundle、token cache、connection resources 与关闭生命周期。
- Capability consumer 从 adapter 获取 Directory、Messaging、Webhook Events、STREAM Events 等窄接口，不再次传 credentials，也不重新构造 SDK。
- Capability presence 直接表达 Provider 支持情况，不维护可能漂移的 support flag，也不提供 dummy unsupported methods。
- 所有 Messaging capability 只向一个明确的 IM user 发送；group、channel、chat、department、tag 与其他 broadcast destination 不进入 public API。
- Webhook 与 STREAM 保留各自的认证、challenge/control-frame、connection 和 ACK 语义，同时通过 `IMEventSink` 完成控制反转。
- Provider adapter 只产生通用 Provider facts，不依赖任何业务 consumer、persistence schema、queue 或 workflow model。
- 为每个 concrete Provider 的每个外部 API operation 和 event entry 建立独立、可审计的验证证据。

**Non-Goals:**

- 不定义业务 recipient、delivery、form、task、approval、workflow 或业务 card-submission model。
- 不规定 `IMEventSink` 使用数据库 inbox、message broker、内存 handler 或其他具体实现。
- 不实现动态插件发现、generic operation dispatcher 或运行时 capability registry。
- 不要求所有 Provider 使用完全相同的 SDK client 数量；adapter 可以隐藏 Provider-specific client bundle。
- 不定义 deployment configuration、credential persistence、rotation orchestration、adapter cache key 或跨进程 adapter singleton。
- 不设计连接配额、leader election、滚动部署、remote revoke/uninstall 或 Provider delivery receipt。
- 不提供 group/channel/chat/department/tag broadcast messaging，也不把 Directory visibility topology 当作 Messaging destination。

## Decisions

### 1. IMProviderAdapter owns one immutable Provider client context

Concrete adapter 由 Provider-specific typed configuration 构造。构造阶段只进行本地 shape validation，不执行远端 credential test，因此即使 candidate credentials 无效，也能够先构造 adapter 再调用 `test_credentials()`。

Adapter configuration 在实例生命周期内不可变。需要使用新 credentials、verification material 或 connection material 时，composition layer 构造新 adapter 并关闭旧 adapter；capability 不得原地替换根 adapter 的 configuration。

Adapter 内部拥有 `ProviderClientContext`。该 context 是实现概念，不进入共享接口；它可以是一个 SDK client，也可以是由 API client、Webhook verifier、STREAM client、HTTP session、token cache 和 rate limiter 组成的 Provider-specific bundle。关键不变量是：每个 client role 由根 adapter 创建或 lazy-memoize，capability acquisition 和 capability method invocation 都不得自行构造相同 role 的新 client。

```python
adapter = adapter_factory.create(provider_config)

credential_result = adapter.test_credentials()
directory_snapshot = adapter.directory.read_snapshot()
message_result = adapter.messaging.send_text(destination, message)

adapter.close()
```

Adapter 还隐藏 concrete SDK 的并发约束。若 SDK client 可并发复用，adapter 可以直接共享；若需要 serialization、pooling 或 per-connection isolation，concrete adapter 在内部处理，capability consumers 不协调 SDK locks。

Alternatives considered:

- 每个 capability 接收 credentials 并自行构造 SDK client。Rejected because credentials、token cache、connection pool、rate limits 与 cleanup 会重复，并且 capability 之间可能观察到不同 Provider session state。
- 将该对象建模为 DDD aggregate root。Rejected because它不拥有业务 entity consistency 或 repository transaction；使用 aggregate 术语会把 infrastructure lifecycle 与 domain lifecycle 混淆。
- 使用全局 Provider SDK singleton。Rejected because不同 Provider configurations、credential revisions 和并发租户必须隔离。

### 2. The root exposes capability views rather than one umbrella method interface

`IMProviderAdapter` 是 capability composition root，不是包含所有方法的巨型接口。每个 view 保持独立 contract，但闭包引用相同 adapter-owned client context。

| Capability view | Initial availability | Shared operation boundary |
| --- | --- | --- |
| Credential testing | All five Providers | `test_credentials()` on the root |
| Directory | All five Providers | Complete Provider identity snapshot |
| Basic Messaging | All five Providers | Destination reachability and `send_text` |
| Dynamic Card Messaging | Slack, Feishu/Lark, Microsoft Teams | Assessment, `send_card`, exact-reference update |
| Webhook Events | Slack, Feishu/Lark, Microsoft Teams | Caller-driven Webhook request handling |
| STREAM Events | Slack, Feishu/Lark | SDK-driven long-running event handling |

Required views are always present. Optional views are absent when unsupported; there is no separate `supports_stream` or `supported_event_transports` result to check before obtaining the view, and unsupported Providers do not implement methods that only return an unsupported error.

```python
class IMProviderAdapter(Protocol):
    def test_credentials(self) -> CredentialTestResult: ...

    @property
    def directory(self) -> IMDirectory: ...

    @property
    def messaging(self) -> IMMessaging: ...

    @property
    def dynamic_card_messaging(self) -> IMDynamicCardMessaging | None: ...

    @property
    def webhook_events(self) -> IMWebhookEvents | None: ...

    @property
    def stream_events(self) -> IMStreamEvents | None: ...

    def close(self) -> None: ...
```

Capability accessors themselves are side-effect free and return views backed by the same root context. A concrete implementation may return stable view objects or lightweight wrappers, but obtaining a view never authenticates credentials, opens a stream connection or creates another SDK client.

### 3. Credential testing is bound to the adapter and independent from transport

`test_credentials()` takes no arguments. It uses only API credential material already bound into the adapter, authenticates against the Provider, identifies a stable Provider tenant and checks baseline API permissions.

It does not test message-destination reachability, Webhook verification material, STREAM connection support or any business operation. Success returns normalized safe facts; authentication, tenant-identification and permission failures are typed. Raw credentials、SDK client objects、raw Provider responses 和 Provider-specific exceptions 不跨越接口。

Transport configuration material remains Provider-specific but belongs to Webhook or STREAM capability construction inside the root adapter. Capability presence, not credential-test output, states whether the adapter implements that transport.

### 4. Directory is an adapter-bound complete-snapshot capability

Directory capability receives no credentials、SDK client 或 generic integration context。它通过 root-owned client context 完成 Provider-specific pagination、department traversal、rate-limit handling 和 error translation。

一次成功调用返回完整 immutable snapshot；任何 page/node failure 都返回 typed failure 且不暴露 partial snapshot。共享 identity facts 只包含 provider user ID、display name、optional Email 和 availability；pagination cursors、raw responses 和 topology details 留在 concrete adapter。Slack、Feishu/Lark、DingTalk 与 Microsoft Teams 的 typed `directory_page_size` 只作为测试 seam 覆盖真实 Provider page-size 参数；默认配置保持原有 wire behavior，WeCom 因不存在分页协议而不暴露该字段。

Directory capability 只读取 Provider directory。如何匹配、reconcile、persist 或消费这些 identity facts 属于调用方。

### 5. Messaging capabilities are personal-user-only and keep operation semantics narrow

Basic Messaging 接收 Provider-specific personal-user destination，测试该用户的 reachability 或发送已经准备好的文本内容。Dynamic Card Messaging 对 normalized card intent 做无副作用 assessment、向同一个明确用户发送卡片并基于 exact Provider message reference 更新同一实例。任何 operation 都不接受 group、channel、chat、department、tag 或其他 broadcast destination。

Messaging methods 不接收 credentials、SDK client、Directory reader 或 consumer business objects。每次 side-effecting method invocation 至多调用一次 Provider operation；adapter 不做隐式 replay。Provider acceptance 与 exact message reference 作为 typed result 返回，不被解释为 end-user delivery。

Provider-specific personal destination shape、markdown/card rendering、message locator 和 error translation 留在 concrete adapter。Slack 使用 user ID 并保留 Provider 返回的 D-channel 与 timestamp；Feishu/Lark 只允许实际实现的 personal receive-id variants；DingTalk 的 robot code 固定来自 adapter-bound client ID；WeCom 只发送一个 `touser`；Microsoft Teams 绑定 trusted service URL、personal conversation 与目标 user ID。授权非生产测试企业允许从 Directory 中选择任一用户作为测试候选；composition 仍需提供该 Provider 发起 personal message 所需的完整 typed destination，尤其是 Microsoft Teams conversation context。

Dynamic Card Messaging 的 `send_card` 和 exact-reference update 必须接收 immutable `OpaqueMetadata`。该值对象只接受唯一 string keys，避免 Provider rendering 时用 `dict` 静默折叠重复 key。Metadata 是 caller 提供的 opaque correlation hint；concrete adapter 不解释其业务含义，并且只把它嵌套编码到每个 `SUBMIT` control，绝不附加到 `OPEN_URL` control。每个 submit control 同时保留原始 `CardAction.action_id` 和 `CardAction.value`：Feishu/Lark 与 Microsoft Teams 使用 nested object，Slack 使用 versioned compact JSON button value。Slack renderer 在任何 Provider call 前检查完整 button value 的 2000-byte UTF-8 limit，超限返回 typed rendering failure。

Normalized card intent 还保留本期 HITL 必需的 required text input、required single-select input 和 ordered actions。Input ID 在一张卡中唯一，single-select option value 在该控件内唯一；存在 input 时至少存在一个 `SUBMIT` action。多个 submit action 是同一份表单的不同业务决策，不复制 input，也不把 selected action 混入 form values。Slack 使用 `input` block、`plain_text_input` 与 `radio_buttons`；Feishu/Lark 使用 schema 2.0 `form`、`input` 与 `select_static`；Microsoft Teams 使用 `Input.Text`、single-select `Input.ChoiceSet` 与多个 `Action.Submit`。三家 callback 均保留 Provider-native form values 与 selected action envelope，adapter 不在此边界组装 consumer submission model。

Submit callback 中返回的 metadata 已经过 end-user-controlled Provider client，必须视为不可信输入，不能作为 authentication 或 authorization evidence。Provider adapter 继续只输出 Provider-native authenticated payload；独立 consumer/decoder 负责解析 Provider-specific submit envelope，并使用自己的可信状态验证 action 与 correlation。Metadata 不替代用于 message mutation 的 exact Provider message reference，也不引入 shared correlation token contract。

### 6. Webhook and STREAM invert control through IMEventSink

`IMEventSink` 是 Provider adapter 唯一依赖的入站 consumer port。它接收一个 transport-authenticated `AuthenticatedIMEvent`，并返回 Provider transport 是否可以发送成功 ACK 所需的最小 outcome：

- `ACCEPTED`: consumer 已接管该 event，Provider 可以收到成功 ACK；identified duplicate 可以折叠为该结果。
- `RETRY`: consumer 未接管该 event，adapter 不得发送成功 ACK，并按照 concrete Provider protocol 返回或触发 retry-compatible failure。

Sink 如何取得 `ACCEPTED` 不属于 adapter contract。它可以同步写入 durable store、发布到可靠 transport，或在测试中保存到 memory collector。Provider adapter 不得导入 sink implementation、persistence model 或 business event handler。

```python
class IMEventSink(Protocol):
    def accept(self, event: AuthenticatedIMEvent) -> EventAcceptance: ...


class IMWebhookEvents(Protocol):
    def handle(
        self,
        request: WebhookRequest,
        sink: IMEventSink,
    ) -> WebhookResponse: ...


class IMStreamEvents(Protocol):
    def run(
        self,
        sink: IMEventSink,
        stop: StopSignal,
    ) -> None: ...
```

#### Webhook control flow

HTTP boundary 把 framework-neutral method、headers、query、body 和 receive time 组成 `WebhookRequest`，再调用 `webhook_events.handle(request, sink)`。Concrete adapter 负责 URL challenge、signature/timestamp/replay verification、decryption 和 Provider-specific response encoding。

Challenge、authentication failure 或 non-event control request 不调用 sink。Authenticated event 只调用 sink 一次；sink 返回 `ACCEPTED` 后 adapter 才返回 success ACK response，返回 `RETRY` 或抛出 unexpected failure 时 adapter 产生 Provider-specific retry-compatible response。

#### STREAM control flow

Runtime 调用 `stream_events.run(sink, stop)` 启动长生命周期 operation。Concrete adapter 建立 Provider SDK connection、注册 callbacks、处理 connection authentication、control frames、reconnect 和 protocol ACK。

Provider SDK callback 收到 business delivery 后，adapter 验证 envelope、解密并构建 `AuthenticatedIMEvent`，随后调用同一个 sink。Sink outcome 在原 callback/connection ownership 内映射成 Provider-specific ACK；ACK ownership 不转移给 sink。Stop signal 请求终止后，run operation 负责停止 reconnect、关闭本 adapter 的 stream resources 并返回。

Webhook 与 STREAM 不共享 request、connection 或 ACK interface；它们只共享 authenticated event 和 sink semantics。这保留了真实控制流，同时避免两套 downstream consumer contract。

### 7. AuthenticatedIMEvent is provider-neutral evidence, not a business event

`AuthenticatedIMEvent` 包含：

- provider and stable Provider tenant ID;
- optional real Provider event ID;
- optional Provider event time and local receive time;
- immutable decrypted Provider-native payload;
- optional Provider-owned event type discriminator.

它不包含 raw verification secret、encrypted request body、HTTP response object、STREAM ACK envelope、SDK client、connection state、local persistence ID 或任何业务 consumer state。

Adapter 只保留 Provider 真正提供且能证明在 redelivery 中稳定的 event ID；不得从 payload hash、timestamp、message reference 或 ACK envelope 合成 event ID。

Provider-native payload 的进一步解释由独立 consumer/decoder 完成。本 change 不定义 card submission、workflow event 或其他业务 event model。

### 8. Do not expose ACK handles to downstream consumers

Alternative design 是让 Webhook/STREAM 返回带 `ack()` / `nack()` 的 delivery handle，或将 stream 表达为 async iterator。它能显式展示 ACK 时序，但会把 Provider connection ownership、ACK deadline 和 exactly-once handle lifecycle 泄漏给所有 consumers，并且与 callback-driven Provider SDK 不自然匹配。

本设计选择 callback sink：adapter 保留 ACK control，sink 只回答是否已经接管 event。这样 Provider-specific protocol complexity 被下拉到 concrete adapter，common consumer 不需要理解 Slack envelope、Feishu handler return value 或 Microsoft Teams Activity response。

### 9. Provider verification is exhaustive and evidence-backed

实现阶段维护 `Provider × capability operation / event entry` coverage matrix。每个适用项都必须具有：

- concrete Provider unit test;
- concrete Provider integration test;
- authorized non-production real API call or real event processing evidence;
- sanitized real request/response or event payload fixture;
- applicable signature-verification and decryption tests.

Shared contract tests不能替代具体 Provider evidence。Fixture 必须先脱敏 plaintext 和 metadata，再使用 test-only material 重新生成 cryptographically valid signature 或 ciphertext；不得提交真实 credential、secret、token 或 key。

## Risks / Trade-offs

- [Long-lived adapter can retain stale credentials] → Adapter configuration is immutable; composition replaces the whole adapter when configuration changes and closes the previous instance.
- [Shared SDK client may not be concurrency-safe] → Concrete adapter owns serialization、pooling 或 dedicated-client decisions inside its private client context。
- [Optional capability access can be ignored by callers] → Required capabilities are non-optional; optional capability absence is explicit and no dummy methods exist.
- [Sink callback can block Provider ACK deadlines] → Sink contract is intentionally limited to safe acceptance; slow business work remains outside the sink implementation.
- [STREAM shutdown differs across SDKs] → Shared contract specifies stop semantics while concrete adapters own SDK-specific cancellation and reconnect suppression.
- [Provider-native payload delays normalization] → This is intentional; generic Provider infrastructure must not guess consumer business schemas.
- [Submit metadata can be modified by an end user or Provider client] → Treat it only as an opaque correlation hint; independent consumers must authorize from trusted state rather than returned metadata.
- [Slack submit metadata can exceed the button-value wire limit] → Render the complete versioned envelope and return a typed failure before any Provider call when its UTF-8 encoding exceeds 2000 bytes.
- [Provider form controls can silently diverge] → Keep the common intent limited to required text and required single-select controls supported by all three card Providers, assert every rendered input/action in concrete tests, and retain Provider-native callback values for independent decoding.

## Migration Plan

1. Introduce `IMProviderAdapter` and Provider-specific configuration types without switching existing callers.
2. Move concrete SDK/client construction into each root adapter and expose capability views backed by the same client context.
3. Change credential testing to `adapter.test_credentials()` and remove transport or credentials arguments from capability methods.
4. Move Directory and Messaging callers to adapter-bound views.
5. Introduce `IMEventSink`, `AuthenticatedIMEvent`, Webhook `handle` and STREAM `run` contracts.
6. Move Provider authentication、challenge/control-frame handling、SDK callbacks 和 ACK mapping into the applicable event capability。
7. Move persistence、queueing、routing 和 business decoding behind independent sink/consumer implementations。
8. Close every applicable verification-matrix cell before enabling a concrete Provider capability.

## Open Questions

- Which concrete Provider SDK clients are thread-safe, and which adapter implementations require internal serialization or a client pool?
- What exact stop/cancellation primitive best fits the implementation runtime while preserving the shared STREAM `run(sink, stop)` semantics?
- Which Provider event identifiers are documented as stable across redelivery rather than only across one transport envelope?
- What normalized generic card intent is shared by the three Dynamic Card Messaging implementations?
- How is a Microsoft Teams personal conversation context acquired and refreshed for a selected Directory user?
