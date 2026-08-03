## Why

Human Input v2 已经在 Dify 主仓库形成 Contact Directory、IM control-plane repository、provider adapter 计划和异步执行基础；如果 EE Go backend 再实现一套 integration CAS、directory sync、reconciliation、worker 与 binding persistence，会让同一业务能力在 Python 和 Go 中出现两个 owner。当前 Dify 与 EE 虽然已有双向依赖，但本 change 必须保证 Human Input admin 这条调用链单向收敛到 Dify，而不是新增一次请求内的 `Dify → EE → Dify` 或 `EE → Dify → EE` 回环。

## What Changes

- 在 EE backend 新增由 Protobuf 描述、由 Kratos 生成和承载的 `EnterpriseHumanInputAdmin` HTTP API；不引入 gRPC server 或 gRPC-Gateway。
- 在 EE `difyclient` 中新增 typed Human Input internal client，把 Organization Contact、IM integration、manual sync、IM identity 与 Organization binding 请求转发给 Dify internal HTTP API。
- 将 provider credential处理、integration CAS、single-active-run、provider directory adapter、reconciliation、worker、Contact projection 与 binding persistence全部保留在 Dify 主仓库，EE 不直接读写 Human Input tables。
- EE 只负责 dashboard administrator 鉴权、Protobuf/HTTP validation、EE-owned human-actor audit、DTO mapping、operation/correlation tracking、超时控制和稳定错误映射；Dify 不接收或保存 EE Dashboard User identity。
- 固定 capability-local 调用方向：EE Dashboard 使用 `EE → Dify`；Dify workspace controller 直接调用同一 Python application service，不能通过 EE Kratos API绕回 Dify。
- 明确排除 EE provider adapter、EE sync worker、EE reconciler、EE Human Input Ent schema/repository、workspace override、Platform/External Contact lifecycle、Email provider、member/workspace CRUD 和自动同步。

## Cross-Repository Ownership

本 change 是该 capability 的 authoritative cross-repository coordination、specification 与 progress checklist。Dify repository 拥有这份跨仓规范以及 Human Input 领域行为和 internal API contract；`dify-enterprise` repository 拥有 EE Go/Protobuf transport implementation、Dashboard authentication/authorization 与 human-actor audit code。

- EE handwritten/generated source 只写入 `dify-enterprise` repository；Dify repository 不承载 EE Go/Protobuf implementation。
- 不要求在 `dify-enterprise` 中复制 OpenSpec、progress checklist 或其他 delivery artifact；本 change 可以直接引用 EE implementation commit 作为交付证据。
- 当前 EE implementation evidence 固定为 commit `935c2a9030a1fe9238d5b469298a7e31cfefb639`。该 commit 只证明 HTTP-only、default-off facade、typed/fake client、service/query/use-case boundary 和 durable audit lifecycle 的本地行为，不证明 Dify internal dependency 或真实跨仓 E2E 已完成。
- 在 Dify internal surface、caller-scoped authentication、projection、workspace no-loop、manual-sync single-owner behavior 与真实跨仓 E2E 全部验证前，feature enablement MUST 保持 **NO-GO**。

## Capabilities

### New Capabilities

- `human-input-v2-ee-admin-transport`: EE Dashboard 的 Kratos HTTP contract、validation、administrator authentication、service registration 与错误边界。
- `human-input-v2-ee-im-sync-adapter`: EE 对 Dify-owned integration、manual sync 与 latest-only read model 的 typed internal HTTP adapter。
- `human-input-v2-ee-contact-binding-adapter`: EE 对 Dify-owned Organization Contact、IM identity 与 Organization binding control-plane 的 typed internal HTTP adapter。

### Modified Capabilities

- 无。

## Impact

- EE API contract：`dify-enterprise/server/pkg/apis/enterprise/v1/` 及其 Kratos HTTP generated bindings。
- EE application/client：`dify-enterprise/server/pkg/enterprise/service/`、负责 audit/orchestration 的 use case、`server/pkg/difyclient/`、HTTP registration 与 Wire composition。
- Dify upstream dependency：需要一个独立 change 提供 Organization Contact projection lifecycle、`/inner/api/enterprise/human-input/*` trusted HTTP surface，并让它与 workspace controllers 共用 Dify Human Input application service。
- EE target commit 已扩展 EE audit database 的 `audit_logs` lifecycle fields；它不新增 Dify DB Human Input Ent schema、EE worker/provider dependency 或 Human Input persistence migration。
- Dify normative specification 来源：Dify Contact Directory / IM control-plane core specs 与 Dify internal API contract；`human-input-v2-api-summary.md` 和 `human-input-v2-api-contracts/specs/human-input-ee-admin-api/spec.md` 仅作为 EE delivery contract 输入。
- EE target commit 的 merge evidence 仅覆盖 local/fake/default-off 测试范围；当前 rollout/feature enablement 结论为 **NO-GO**。
