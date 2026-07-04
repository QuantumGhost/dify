# 2026-07-02 HITL IM Planning

## What changed

- Added `.harness/docs/TEMP-task-document.md` to capture the HITL IM implementation objective, deadline, constraints, and recommended architecture path.
- Added `.harness/docs/TEMP-progress-document.md` to record the planning round status, sources reviewed, findings, and next actions.
- Updated the planning artifacts after provider selection to lock the first IM provider to `Feishu/Lark`.
- Added the `card-first` delivery rule and the provider capability abstraction requirement to the plan.
- Added the `env-backed for demo, tenant-scoped in production` provider configuration strategy.
- Marked `file` and `file-list` as link-fallback-only for the first Feishu implementation.
- Moved `paragraph` back into the first-cut scope, with an explicit distinction between card rendering and inline input UX equivalence.
- Added the `webhook vs polling` ingress abstraction requirement.
- Added a layered provider testing strategy to compensate for limited Feishu callback E2E automation.
- Updated the ingress recommendation from `webhook-first` to `official SDK long-connection first` for Feishu.
- Added an explicit `official SDK first` rule for IM provider implementation.
- Narrowed the expected Python SDK choice to `lark-oapi` plus `lark-channel-sdk`, based on official Feishu sources.
- Implemented the first backend Feishu HITL IM slice:
  - generic IM delivery type
  - account IM binding model/service
  - env-backed provider config store
  - provider-neutral IM notification entities
  - Feishu card builder
  - IM delivery task and dispatcher
  - webhook ingress service
  - long-connection service
  - trigger callback endpoint
  - current-account manual binding API
- Refined the architecture after review:
  - IM recipient payload now stores stable binding references instead of provider-specific transport identities
  - Human Input repository now resolves IM bindings through a core repository boundary
  - account IM binding writes now commit explicitly and translate uniqueness conflicts
  - env-backed provider config now supports an explicit tenant owner
  - webhook/ws callback business rejections no longer bubble into generic 500s
- polling was removed from the config surface; only webhook and stream remain valid ingress modes
- Added a binding-only Feishu OAuth flow that:
  - starts from the current logged-in Dify account
  - exchanges the Feishu code
  - materializes or refreshes `AccountIMBinding`
  - does not participate in Dify sign-in
- Added the minimal `/account` Feishu binding UI:
  - manual `open_id / user_id` binding
  - explicit Feishu OAuth binding action
  - localized copy and focused frontend tests

## Why it changed

- The repo did not contain the temporary planning artifacts required by the current squad development workflow.
- The HITL IM work needs a carried-forward plan because the required scope crosses backend runtime, delivery infrastructure, callback handling, and frontend configuration.
- The user explicitly asked for an implementation plan that should guide real production-facing work instead of a one-off demo patch.
- The user clarified that IM approval must happen inline in IM cards when possible, and links are only an explicit fallback for unsupported form capabilities.
- The user also clarified that demo credentials may come from environment variables, but production must support tenant-level provider configuration.
- The user also clarified that `paragraph` still needs to be rendered in cards and should not be dropped from the first cut.
- The user also clarified that provider ingress should not be hard-wired to webhooks because polling matters for enterprise deployments.
- The user also required that IM integrations should use the official SDK unless a required capability is missing.
- The user explicitly corrected the OAuth scope: Feishu OAuth is only for automatically creating IM bindings, not for Feishu login.
- The user also asked for the code to remain production-oriented, which required keeping the binding OAuth flow separate from the existing sign-in OAuth surface.

## How it was verified

- Read the Feishu PRD through `lark-cli docs +fetch`.
- Reviewed the official Feishu card documentation for card JSON v2 interactive components and card interaction callbacks.
- Reviewed current HITL runtime, repository, controller, and delivery-related source files in the repo.
- Cross-checked existing external-channel semantics with current CLI E2E fixtures and tests.
- Checked the available demo Feishu env keys without exposing secret values.
- Reviewed official Feishu sources indicating that the Python server SDK supports API calls plus both webhook and long-connection callback handling.
- Ran focused backend verification:
  - `uv run --project api pytest ...` on all changed-unit-test slices
  - aggregate result after the OAuth binding additions: `73 passed`
  - `uv run --project api ruff check ...` on changed files
- Ran focused frontend verification:
  - `pnpm -C web test 'app/account/(commonLayout)/account-page/__tests__/feishu-binding-card.spec.tsx'`
  - `pnpm -C web exec eslint 'app/account/(commonLayout)/account-page/feishu-binding-card.tsx' 'app/account/(commonLayout)/account-page/client.ts' 'app/account/(commonLayout)/account-page/__tests__/feishu-binding-card.spec.tsx'`
  - `pnpm -C web exec eslint 'i18n/*/common.json'`

## Known risks or follow-up work

- The referenced Figma design file could not be read with the current access path, so UI-level details are still partially unverified.
- Provider capability mapping still needs a final field-by-field verification before coding starts, especially for multiline text and file inputs.
- `Paragraph` submission UX in cards still needs final implementation-level confirmation against actual Feishu component behavior.
- Tenant-level configuration persistence and admin UI are still planning items, not yet schema-level implementation tasks.
- True polling-mode support for card interaction return paths still needs implementation-stage validation if it is added later.
- The current demo config still resolves to `webhook`, so long-connection mode is implemented but not yet the active deployed path.
- Feishu provider installation/config ownership is still env-backed; tenant-scoped persisted provider config remains the main production follow-up.

## Mergeability follow-up

- After refreshing `upstream/main`, a non-destructive merge rehearsal confirmed that `feat/hitl-im` still merges cleanly into the latest `upstream/main` (`c080e2c3b8`) even though the branch is now behind by 35 commits.
- A real merge from `upstream/main` was then completed on `feat/hitl-im` after backing up the conflicting local untracked files under `/tmp/dify-human-input-backup-20260703-132019`.
- The resulting merge commit is `d402febffb`.
- Two merge-after-fixups were required:
  - switch `api/tasks/human_input_im_delivery_task.py` to Dify-owned HITL entities after graphon `0.6.0`
  - align the workflow app runner notification test with the new pause reason enrichment flow
- A non-destructive merge rehearsal also confirmed that `feat/hitl-im` merges cleanly into `upstream/feat/hitl-file-in-body`.
- A rehearsal against `upstream/feat/agent-hitl-ask-human` produced conflicts in shared HITL persistence/runtime files, especially:
  - `api/core/repositories/human_input_repository.py`
  - `api/models/human_input.py`
  - several Agent v2 ask-human runtime files
- The conflict-heavy branch is built on an older base and changes Agent v2 ask-human pause/resume semantics, so the current IM slice is still mergeable there, but not cheaply.
- A local untracked HITL node refactor still reuses `core.workflow.human_input_adapter.DeliveryChannelConfig`, which is a positive sign that the IM delivery channel extension can survive the newer node structure with moderate follow-up work rather than a rewrite.
- Post-review hardening also fixed:
  - OAuth link token revocation timing
  - dispatcher cache invalidation on provider credential rotation
  - manual binding whitespace normalization

## Untracked code convergence follow-up

- The untracked `api/core/workflow/nodes/human_input/form_processing.py`, `hitl.py`, and `node.py` files are currently not imported by any tracked code.
- Those files overlap conceptually with the tracked Dify-owned HITL boundary/callback modules and with graphon's human-input runtime, so they are best treated as an unintegrated spike, not as a second live implementation.
- The `create_user_tenant` helper chain is different:
  - `api/dev/create_user_tenant.py`
  - `dev/create-user-tenant`
  - `api/tests/unit_tests/dev/test_create_user_tenant.py`
  form a coherent, internally used slice and should be either tracked together or removed together.
- `api/test_isinstance.py` and `api/controllers/web/hitl-service-api-file.sh` appear to be scratch / manual-debug artifacts and should be removed unless someone explicitly wants to preserve them outside the main runtime tree.
