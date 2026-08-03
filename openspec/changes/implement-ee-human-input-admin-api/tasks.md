> **Cross-repository execution boundary**
>
> This Dify source change is the authoritative cross-repository specification and progress checklist. Dify owns coordination/specification and the Human Input domain/internal contract; `dify-enterprise` owns its Go/Protobuf transport implementation, authentication, audit, handwritten code, and generated code. No duplicate EE OpenSpec or progress artifact is required. EE implementation evidence is commit `935c2a9030a1fe9238d5b469298a7e31cfefb639`, whose verified scope is HTTP-only, default-off, and local/fake behavior. Dify dependencies and real cross-repository E2E remain incomplete, so feature enablement is **NO-GO**.

| Sections | Target repository | Blocking dependency |
| --- | --- | --- |
| 1 | `dify` | Dify Human Input application service and internal API change |
| 2–5 | `dify-enterprise` | Section 1 contract freeze |
| 6 | `dify` + `dify-enterprise` | Sections 1–5 and a deployed/testable Dify internal API |
| 7 | `dify-enterprise` for implementation; `dify` for this plan validation only | Section 6 contract and failure verification |

## 1. Freeze The Dify Internal API Dependency

- [ ] 1.1 Confirm the separate Dify change owns `/inner/api/enterprise/human-input/*`, reuses the Dify Human Input application service used by workspace controllers, and contains no callback to the EE Human Input API.
  - Evidence: The Dify internal surface has not been implemented or verified.
- [ ] 1.2 Freeze the Dify-owned internal JSON request/response semantics, provider/status/result enum values, pagination defaults, stable error codes, and operation/correlation metadata for all twelve admin operations; the internal contract MUST NOT accept an EE human actor or require one-to-one shape identity with the EE public Protobuf.
  - Evidence: The Dify internal contract has not been implemented or frozen.
- [ ] 1.3 Add versioned semantic cross-repo contract fixtures for integration CAS, secret replace/preserve, sync latest/results, Contact/identity projections, binding mutations, safe diagnostics, and error responses; verify the EE-required mapping without requiring unrelated fields or the overall contract shape to match.
  - Evidence: Versioned cross-repository fixtures do not exist yet.
- [x] 1.4 Record the Dify internal API as a blocking upstream dependency; do not mark EE end-to-end integration complete while only fake-client tests are available.
- [ ] 1.5 Confirm the Dify upstream owns an idempotent `OrganizationContactProjectionService` with initial backfill, bounded ensure before Organization Contact reads/manual sync, periodic reconciliation for Account create/update/disable/delete, stable Contact-ID reuse for the same Account, current-state omission for unavailable Accounts, and `joined_at` projected from `Account.created_at` rather than `Contact.created_at`.
  - Evidence: The projection lifecycle and `joined_at` source have not been verified against Dify.

## 2. Kratos HTTP Contract And Code Generation

- [x] 2.1 Add `server/pkg/apis/enterprise/v1/human_input.proto` with the API-summary enums, credential oneofs, messages, twelve `EnterpriseHumanInputAdmin` methods, validation rules, field numbers, JSON names, and `/v1/dashboard/api/human-input/*` `google.api.http` mappings.
- [ ] 2.2 Generate the enterprise Protobuf validation and Kratos HTTP bindings with `make proto-gen WHAT=enterprise`, and add a descriptor test that detects route, enum number, field number, JSON name, or required-validation drift.
  - Evidence: Target descriptor coverage locks only three of seven enums and selected fields; the standard generator path has not been verified.
- [x] 2.3 Add a focused architecture test or registration assertion proving Human Input is registered only through the Kratos HTTP server and does not add an enterprise gRPC server or gRPC-Gateway path.
- [x] 2.4 Add Human Input enterprise error reasons for invalid request, upstream unauthorized/not found, stale revision, binding conflict, provider unavailable, and sanitized upstream/internal failure.

## 3. Typed Dify Human Input Client

- [x] 3.1 Add typed `difyclient` request/response models, a `HumanInputControlPlaneClient` interface, and a deterministic fake client without importing EE Ent entities or provider SDK types.
- [ ] 3.2 Implement and test Organization Contact list mapping with member-name/email filters, page/limit defaults, `joined_at` sourced from Dify `Account.created_at`, avatars, and Organization bindings; do not relabel Contact projection creation time as membership time.
  - Evidence: EE mapping exists, but the Dify `Account.created_at` source has not been verified end to end.
- [x] 3.3 Implement and test integration get/upsert/delete/test calls, preserving the complete `integration_id + config_version` CAS token, read-only effective deployment event transport projection, and every provider-specific replace-or-preserve credential operation; omit Integration-level mode fields from upsert/test and do not expose tenant-selectable supported modes.
- [x] 3.4 Implement and test manual sync create, latest run, and latest result calls with real bucket validation, `page / limit / total`, captured integration revision, `finished_at`, and omission of `started_by` and repeated summary.
- [x] 3.5 Implement and test IM identity list plus binding create/delete/test calls, including complete Contact/binding path ownership and typed reachable diagnostics.
- [x] 3.6 Apply bounded timeouts, correlation propagation, and safe-read-only retries; add tests proving CAS, binding, and sync mutations are not blindly retried after ambiguous connection failures.
- [x] 3.7 Add malformed-response, unknown-error-code, timeout, connection failure, and cancellation tests that preserve typed upstream outcomes without logging raw response bodies.

## 4. EE Audit/Orchestration Use Case And Kratos Service

- [ ] 4.1 Add failing use-case tests for operation/correlation ID creation, EE-owned mutation audit start and success/rejected/unknown outcomes, one upstream command per attempt, and current-state/manual reconciliation after ambiguous timeout; prove the use case performs no provider, Dify database, reconciliation, or worker action.
  - Evidence: Durable audit lifecycle is covered locally, but current-state/manual reconciliation after ambiguous outcomes is not implemented.
- [x] 4.2 Implement the Human Input admin use case as the owner of EE actor audit and mutation orchestration while returning transport-neutral upstream results without reimplementing Dify business rules; the five reads remain direct `HumanInputQuery` service dependencies.
- [x] 4.3 Add failing Kratos service tests for Protobuf defaulting, DTO mapping, optional timestamps/fields, stable error mapping, safe provider diagnostics, and refreshed Contact/integration/run projections.
- [x] 4.4 Implement all twelve `EnterpriseHumanInputAdmin` service methods as thin Protobuf/query-or-use-case mappers.
- [x] 4.5 Extract the authenticated Dashboard User from trusted Kratos context, record that identity only through the EE audit boundary, and propagate only operation/correlation metadata to the Dify client; test that public actor/Organization spoofing cannot reach either boundary and that no EE User ID is converted to or sent as a Dify Account actor.
- [x] 4.6 Register the generated Kratos HTTP service in `server/pkg/enterprise/server/http.go` and add the service, query, use case, gateway, audit recorder, client, and fake boundaries to the existing Wire provider sets.

## 5. Security, Error, And Architecture Boundaries

- [ ] 5.1 Add secret-redaction regression tests for Protobuf JSON, client payload logging, Kratos errors, traces, metrics, and malformed Dify responses so plaintext, masked values, ciphertext, tokens, and credential-bearing raw bodies cannot escape.
  - Evidence: Focused redaction checks exist, but the complete secret trace/metrics/malformed-response matrix is not covered.
- [x] 5.2 Implement allow-list request/response mappers and stable Dify-error-code to enterprise-error mapping; reject message-substring-based business error inference.
- [x] 5.3 Add an EE architecture test proving the Human Input dependency graph contains no Dify Ent schema/repository, raw SQL, provider adapter, sync worker, reconciler, distributed lock, or Human Input persistence cache.
- [ ] 5.4 Add a capability call-graph check or review guard proving EE Human Input only calls Dify and that Dify Human Input never calls the EE Human Input façade. Permit license/edition/Organization facts through narrow capability ports or policy snapshots resolved at the entry/composition boundary; do not ban every `EnterpriseService` capability by name.
  - Evidence: The EE side is locally constrained, but the real Dify workspace no-loop path has not been verified.
- [ ] 5.5 Add structured upstream metrics/logs for operation name, latency, result class, status code, and correlation ID while excluding credentials and Contact/identity PII.
  - Evidence: Structured upstream metrics are not implemented.
- [ ] 5.6 Restrict the Dify Human Input internal surface to an EE-identifying caller credential, mTLS identity, or equivalent caller-scoped authentication, and test that another holder of a generic internal credential cannot create a mutation that bypasses the EE human-actor audit boundary.
  - Evidence: Dify caller-scoped authentication has not been implemented.

## 6. Cross-Repository Contract And Failure Testing

- [ ] 6.1 Run the versioned semantic contract fixtures against both the EE typed client and the real Dify internal API, resolving every EE-required field, enum, pagination, timestamp, secret-operation, and stable-error mismatch without requiring the public and internal contracts to be globally isomorphic.
  - Evidence: There are no versioned fixtures or real Dify internal API run.
- [ ] 6.2 Add integration coverage for Contact list, integration get, latest run/results, and identity search through `EE Kratos HTTP -> difyclient -> Dify internal HTTP`.
  - Evidence: Coverage stops at local/fake adapters; the real cross-repository read path is unverified.
- [ ] 6.3 Add integration coverage for integration CAS mutation, connection test, manual sync trigger, binding create/delete, and binding reachability through the same one-way call chain.
  - Evidence: Coverage stops at local/fake adapters; the real cross-repository mutation path is unverified.
- [ ] 6.4 Add ambiguous-timeout tests proving the EE layer records an `unknown` audit outcome, does not replay mutations, and supports current-state/manual reconciliation through current integration, latest run, or refreshed Contact reads without rewriting the durable audit outcome.
  - Evidence: Current-state/manual reconciliation is not covered end to end.
- [ ] 6.5 Verify the Dify workspace endpoints invoke the shared Python Human Input application service directly and never route through the EE Kratos API, including the edition-denied Organization mutation path.
  - Evidence: The real Dify workspace call graph and edition-denied path are unverified.
- [ ] 6.6 Verify one manual sync produces provider fetch, reconciliation, persistence, and result reads only in Dify; assert no corresponding EE worker/provider/database activity exists.
  - Evidence: Single-owner manual-sync behavior has not been verified against a real Dify deployment.

## 7. Generation, Validation, And Rollout Readiness

- [ ] 7.1 Run `make proto-gen WHAT=enterprise` and `make generate`, format generated and handwritten Go/Proto sources, and review generated drift for HTTP-only Human Input registration.
  - Evidence: Target generated sources exist, but the standard full-network generation commands were not verified.
- [ ] 7.2 Run focused client, fake-client, use-case, EE audit, Kratos service, authentication, error-mapping, redaction, architecture, and cross-repo contract tests.
  - Evidence: Focused local tests passed at the target commit, but caller authentication and real cross-repository contracts are incomplete.
- [ ] 7.3 Run `make lint` and `make test` in `dify-enterprise`, recording environment-dependent Dify integration coverage separately without treating skipped integration tests as local success.
  - Evidence: Full `make lint` and `make test` verification has not been recorded.
- [ ] 7.4 Enable the EE Human Input admin feature gate only after the Dify internal dependency is deployed; validate read operations before CAS, manual sync, and binding mutations.
  - Evidence: Enablement has not been executed and remains **NO-GO**.
- [ ] 7.5 Exercise rollback by disabling the EE feature gate and HTTP entry while confirming Dify-owned sync runs, workers, and persisted state continue independently.
  - Evidence: Rollback has not been exercised against a real Dify deployment.
- [x] 7.6 Run `openspec validate implement-ee-human-input-admin-api --strict` and re-read the proposal, design, specs, tasks, and affected EE comments/docstrings for Kratos terminology, single-owner semantics, and call-graph consistency.
  - Evidence: Strict validation passed against the authoritative source change after target-commit alignment.
