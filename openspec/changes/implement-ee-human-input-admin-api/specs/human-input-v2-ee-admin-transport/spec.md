## ADDED Requirements

### Requirement: EE Dashboard MUST 通过 Kratos HTTP 暴露完整的 Human Input admin API

EE backend MUST 在 `dify.enterprise.api.enterprise` package 中定义 `EnterpriseHumanInputAdmin` Protobuf service，并 MUST 使用 Kratos 的 Protobuf HTTP code generation 和 `google.api.http` annotations 暴露 API summary 中的十二个 `/v1/dashboard/api/human-input/*` endpoint。该 capability MUST 保持 HTTP-only 与 default-off，MUST NOT 新增 gRPC server registration，也 MUST NOT 引入 gRPC-Gateway。

#### Scenario: Kratos 注册 Human Input admin HTTP service
- **WHEN** enterprise server 完成 API generation 与 HTTP composition，且 `human_input_enabled` gate 已启用
- **THEN** 十二个 service method 对应的 Kratos HTTP handler MUST 全部注册，并 MUST 由现有 Kratos middleware chain处理 validation、authentication 与 error encoding

#### Scenario: 实现者尝试增加 gRPC transport
- **WHEN** Human Input admin service 被接入 enterprise server
- **THEN** implementation MUST NOT 注册对应 gRPC server，也 MUST NOT 增加 grpc-gateway proxy 或 gateway-specific mapping

### Requirement: Transport MUST 在调用 Dify client 前完成强类型校验与默认值处理

Protobuf contract MUST 保留 API summary 中的 provider、status、read-only effective deployment `DISABLED / WEBHOOK / STREAM` event transport mode、result、removal reason、credential、Contact、identity、binding、sync run 与 pagination shape。Integration upsert/test request MUST NOT包含event transport mode或tenant-selectable supported modes。Request-specific required enum、ID、完整 CAS token、secret operation、page 和 limit MUST 由 PGV 或 request mapper 在调用 Dify 前拒绝；省略 page/limit 时 MUST 分别使用 `1` 和 `20`。

Response `IMIntegration` MUST 使用 status-dependent semantic validation：`status` 始终为 known nonzero value；`NOT_CONFIGURED` 的 configured projection MUST 保持 empty/absent/zero，因此 provider、`webhook_url`、`permission_hint`、integration ID、config version 与 configured/updated timestamp MUST NOT 被无条件要求为非零或存在，其 effective event mode MAY 为 unspecified 或 known read-only mode；其他 status MUST 具有 known nonzero provider、nonempty integration ID、positive config version、nonzero configured/updated timestamps 与 known nonzero effective event mode。PGV 只拥有 local wire-shape/defined-enum validation，data adapter MUST 是这些 internal response invariants 的唯一 owner；低层 HTTP client、use case 与 Kratos service MUST NOT 重复拥有该组合校验。

#### Scenario: 请求包含非法 enum 或 CAS token
- **WHEN** 请求包含 unspecified required enum、空 ID、非正 config version 或越界 pagination
- **THEN** Kratos validation MUST 在调用 Human Input use case 与 Dify internal client 之前拒绝请求

#### Scenario: Latest results 未传 pagination
- **WHEN** 管理员指定真实 result bucket 但省略 page 和 limit
- **THEN** EE service MUST 向 Dify client 传递 page `1` 与 limit `20`

#### Scenario: Dify 返回未配置的 integration projection
- **WHEN** response status 为 `NOT_CONFIGURED`，provider、`webhook_url`、`permission_hint`、integration ID、config version 与 configured/updated timestamps 为 empty/absent/zero，event mode 为 unspecified 或 known read-only mode
- **THEN** data adapter MUST 接受该合法 projection，transport MUST NOT 因 configured fields 为 empty/absent/zero 而拒绝 response

#### Scenario: Dify 返回语义不完整的 configured integration
- **WHEN** response status 不是 `NOT_CONFIGURED`，但缺少 known provider、integration ID、positive version、timestamps 或 known nonzero event mode
- **THEN** data adapter MUST 在 response 到达 use case/service 前返回 typed malformed-upstream outcome，且其他 layer MUST NOT 复制该 semantic validator

#### Scenario: Request attempts to set event transport mode
- **WHEN** an Integration upsert or test request contains an event transport mode override
- **THEN** Kratos validation MUST reject the request before the Human Input use case or Dify internal client is invoked

### Requirement: Administrator identity MUST 只由EE audit boundary拥有

所有 Human Input admin endpoint MUST 复用 EE Dashboard 的 authentication 与 enterprise-administrator authorization。EE MUST 从可信 request context提取Dashboard User；每个 mutation MUST 在调用 Dify 前以 unique operation ID 同步持久化单条 `started` audit row，并在 gateway 返回后以 `started` CAS 将同一 row 完成为 `success`、`rejected` 或 `unknown`。Public request body MUST NOT 接受actor ID或Organization ID；service-to-service request MUST 只向Dify传播operation/correlation metadata，不得传播EE User ID或要求Dify保存external principal。Dify Human Input internal surface MUST 使用能够识别EE caller的service credential、mTLS identity或等价caller-scoped authentication，避免其他internal caller绕过EE audit直接执行同权mutation。default-off composition MUST NOT 连接 audit database。

#### Scenario: 未认证调用 admin endpoint
- **WHEN** 请求没有有效 Dashboard session/token 或不具备 enterprise administrator 权限
- **THEN** Kratos middleware/service MUST 返回现有 `401/403` error，且 MUST NOT 调用 Dify internal API

#### Scenario: 已认证管理员执行 mutation
- **WHEN** 管理员 upsert integration、触发 sync 或修改 binding
- **THEN** EE use case MUST 在调用Dify前同步插入单条`started` row，并在结果明确后以CAS更新同一row为`success`或`rejected`；Dify request MUST 不包含human actor，且EE-originated mutation MUST 不填充Dify Account-specific actor字段

#### Scenario: Mutation发生ambiguous timeout
- **WHEN** EE无法判断Dify是否已接受mutation
- **THEN** EE audit completion MUST 以CAS将同一row记录为`unknown`并关联correlation ID，MUST NOT blind retry；后续只MAY通过current-state read与manual reconciliation解析或补充该outcome

#### Scenario: Mutation 已返回但 audit Complete 失败
- **WHEN** Human Input gateway 已产生 mutation outcome，但 audit `Complete` 无法把 `started` row 更新为 terminal outcome
- **THEN** EE MUST 同时返回 mutation outcome 与 audit-completion-unavailable signal；遗留 `started` row MUST 只表示 audit completion unresolved，MUST NOT 被解释为 mutation outcome

#### Scenario: Default-off server composition
- **WHEN** Human Input admin feature 未启用
- **THEN** server MUST NOT 注册可达的 Human Input HTTP facade，也 MUST NOT 建立 audit database connection

#### Scenario: 非EE caller尝试调用Human Input internal mutation
- **WHEN** caller不能证明EE-specific service identity，即使其持有其他generic internal credential
- **THEN** Dify MUST 拒绝该mutation，使所有EE admin human-actor audit保持完整

### Requirement: Secret-bearing transport MUST 支持 replace-or-preserve 且不得泄露 secret

Provider credential secret MUST 表达为非空 replacement 或 `preserve_original_value`。EE 只校验和转发该 command，不缓存、持久化、解密或回显 secret。Response、Kratos error、structured log、trace attribute 与 generated API documentation MUST NOT 包含 plaintext、masked value、ciphertext 或 hash-derived secret。

#### Scenario: 管理员保留已存在 secret
- **WHEN** update request 对一个 secret 使用 `preserve_original_value`
- **THEN** EE MUST 原样转发 preserve operation，由 Dify 判断其是否有效，并 MUST NOT 尝试读取现有 secret

#### Scenario: Dify 返回 secret-related validation error
- **WHEN** Dify 拒绝 first-create preserve 或空 replacement
- **THEN** EE MUST 返回稳定的 sanitized invalid-request error，且 MUST NOT 将 Dify raw body 或 credential内容写入日志

### Requirement: EE transport MUST 稳定映射 Dify internal errors

EE MUST 把 Dify typed internal error映射为既有 enterprise error：invalid input 为 `400`，unauthenticated/unauthorized 为 `401/403`，not configured/not found 为 `404`，stale revision或 binding conflict 为 `409`，provider diagnostic按 service contract 返回 safe typed response，unexpected upstream failure 为 sanitized `502/500`。EE MUST NOT 根据 error message string重新推断业务语义。

#### Scenario: Dify 返回 stale revision
- **WHEN** internal client 收到稳定的 stale-revision error code
- **THEN** Kratos transport MUST 返回 conflict error并保留 correlation context，但 MUST NOT 自动重试 mutation

#### Scenario: Dify internal API 不可用
- **WHEN** upstream timeout、connection failure 或 malformed response发生
- **THEN** EE MUST 返回 sanitized upstream failure并记录 endpoint operation、latency 与 correlation ID，不得记录 request secret或完整 response body

### Requirement: EE Human Input admin surface MUST 保持 Organization-scoped 与 narrow

该 service MUST NOT 增加 member/workspace CRUD、Platform/External Contact lifecycle、workspace override、Email provider、node migration、notification center、task list 或 CLI todo endpoint。Organization scope MUST 由 EE deployment和 trusted Dify internal contract确定，而不是来自任意 client-supplied Organization ID。

#### Scenario: 客户端请求 workspace-owned operation
- **WHEN** EE admin client需要 Platform/External Contact、workspace override 或 Email provider mutation
- **THEN** `EnterpriseHumanInputAdmin` MUST 不提供相应 service method，并 MUST 保持这些能力由 workspace-owned surface管理

### Requirement: EE service boundary MUST 区分 query 与 mutation orchestration

五个 read method（Contact list、integration get、latest run、latest results 与 IM identity list）MUST 由 Kratos service 直接依赖 consumer-owned `HumanInputQuery`。七个 mutation method（integration upsert/delete/test、manual sync create 与 binding create/delete/test）MUST 由 service 调用 `HumanInputUsecase`，再通过 `HumanInputGateway` 执行。Use case MUST 只拥有 mutation orchestration 与 durable audit，不得接管 query 或 Dify business rule。

#### Scenario: Kratos service 执行 read
- **WHEN** 任一 Human Input read method 被调用
- **THEN** service MUST 直接调用 `HumanInputQuery`，MUST NOT 为 read 创建 mutation audit 或绕过 data adapter semantic validation

#### Scenario: Kratos service 执行 mutation
- **WHEN** 任一 Human Input mutation method 被调用
- **THEN** service MUST 通过 `HumanInputUsecase`、durable audit 与 `HumanInputGateway` 执行一次 command attempt，MUST NOT 直接调用低层 HTTP client

### Requirement: Feature enablement MUST 等待真实跨仓依赖

EE commit `935c2a9030a1fe9238d5b469298a7e31cfefb639` MUST 只作为 HTTP-only、default-off、local/fake implementation evidence。Operation/correlation metadata 只支持 current-state read 与 manual reconciliation，不承诺自动改写既有 audit outcome。在 Dify internal surface、projection、caller-scoped authentication、真实跨仓 E2E、workspace no-loop 与 manual-sync single-owner behavior 全部完成前，feature enablement MUST 保持 **NO-GO**。

#### Scenario: 仅 target commit 的 local/fake tests 通过
- **WHEN** rollout review 只有 EE target commit 的 descriptor、fake-client、service/use-case 与 default-off evidence
- **THEN** review MUST NOT 宣称真实 Dify integration 或 outcome reconciliation 已验证，并 MUST 保持 feature disabled
