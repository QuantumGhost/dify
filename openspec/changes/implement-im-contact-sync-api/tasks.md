## 1. Provider Adapter Foundation

- [x] 1.1 Add the minimal backend dependency and provider adapter interfaces needed to read Feishu/Lark directory data through the official server-side SDK boundary.
- [x] 1.2 Implement provider-neutral normalization from Feishu/Lark SDK responses into `ProviderDirectoryEntry` values and safe connection diagnostics.
- [x] 1.3 Add unit tests covering directory-entry normalization, provider-user-ID extraction, normalized-email extraction, and sensitive-error sanitization for the provider adapters.

## 2. IM Sync Application Services

- [x] 2.1 Add an `IMSyncManagementService` that orchestrates integration read/update/delete, connection test, manual sync trigger, latest-run summary, and latest-result pagination through the existing repositories.
- [x] 2.2 Add the asynchronous manual-sync execution flow that creates or reuses the single active run, enqueues background work, loads reconciliation snapshots, calls `SyncReconciler`, and applies revision-guarded plans.
- [x] 2.3 Preserve the canonical latest-only sync result contract with the `added / not_matched / failed / removed / skipped` buckets and add service-level tests for active-run reuse, stale revision rejection, and latest-result paging rules.

## 3. Contact Binding Integration

- [x] 3.1 Add a `ContactIMBindingService` that lists synced IM identities, including search by provider user ID, display name, and email.
- [x] 3.2 Implement contact-scoped IM binding create/delete flows that only allow current `WORKSPACE` or `PLATFORM` contacts and reject `EXTERNAL`, `ABSENT`, or deleted contacts.
- [x] 3.3 Implement EE workspace override set/reset flows without rewriting organization bindings, and verify the existing effective-binding resolution still applies `workspace override > organization binding > Email fallback`.
- [x] 3.4 Add unit and integration tests proving unmatched sync results never auto-create contacts or bindings and that invalidated bindings disappear from effective binding resolution after integration replacement.

## 4. Console API Wiring

- [x] 4.1 Replace the IM-related stub handlers in `api/controllers/console/workspace/human_input.py` with service-backed implementations for integration read/update/delete/test and manual sync latest-only reads.
- [x] 4.2 Replace the identity-search, contact binding, and workspace override stub handlers with service-backed implementations that preserve the existing DTO contract and transport-neutral error mapping.
- [x] 4.3 Update or add nearby module/function docstrings and controller tests so the new IM management routes document their invariants, revision rules, and contact-type guards.

## 5. Verification And Coverage

- [x] 5.1 Add focused repository, service, and controller tests for manual sync success, active-run deduplication, stale revision apply, latest-result bucket validation, identity search, binding writes, and override reset behavior.
- [x] 5.2 Add or update concurrency tests for the async sync path and binding-related current-state transitions where the existing contract depends on serialization or CAS semantics.
- [x] 5.3 Verify the new or changed backend modules for this change reach at least 90% test coverage and record the targeted test commands needed to reproduce the verification.

  Verification evidence:

  - Full targeted regression:
    `uv run --project api pytest -q api/tests/unit_tests/core/human_input_v2/im_integration api/tests/unit_tests/repositories/human_input_v2/contact_directory api/tests/unit_tests/repositories/human_input_v2/im_integration api/tests/unit_tests/services/human_input_v2/test_im_contact_binding.py api/tests/unit_tests/services/human_input_v2/test_im_provider.py api/tests/unit_tests/services/human_input_v2/test_im_sync.py api/tests/unit_tests/tasks/test_human_input_im_sync_task.py api/tests/unit_tests/controllers/console/workspace/test_human_input_im_sync.py`
    passed with 293 tests.
  - Coverage:
    `uv run --project api pytest -q api/tests/unit_tests/repositories/human_input_v2/contact_directory api/tests/unit_tests/repositories/human_input_v2/im_integration api/tests/unit_tests/services/human_input_v2/test_im_contact_binding.py api/tests/unit_tests/services/human_input_v2/test_im_provider.py api/tests/unit_tests/services/human_input_v2/test_im_sync.py api/tests/unit_tests/tasks/test_human_input_im_sync_task.py --cov=repositories.human_input_v2.contact_directory.repository --cov=repositories.human_input_v2.im_integration.repository --cov=services.human_input_v2.im_contact_binding --cov=services.human_input_v2.im_provider --cov=services.human_input_v2.im_sync --cov=tasks.human_input_im_sync_task --cov-report=term-missing`
    passed with 172 tests and 96% aggregate coverage: Contact repository 92%, IM repository 95%, contact binding 94%, provider 99%, sync 97%, and task 100%.
  - Static verification:
    `uv run --project api ruff format --check api && uv run --project api ruff check api && git diff --check`
    passed.
