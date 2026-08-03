# Local Verification and Coverage Receipt — 2026-08-03

本 receipt 记录同一份最终 production 内容上的本地测试与 coverage 结果。它仅证明仓库内可重复执行的测试、静态检查与覆盖率，不是 Provider 真实请求、响应、事件 payload 或独立密码学证据，因此不补齐 evidence matrix 中的 `real_execution`、`sanitized_fixture` 或 `independent_crypto` 单元格。

根目录的可变 `coverage.json` 未被用作最终证据。覆盖率由下述两个独立的 `/tmp` JSON 产物聚合，并固化为本 receipt 中的 numerator / denominator；临时 JSON 不属于持久证据。

## Production content fingerprint

Fingerprint 覆盖全部 `api/core/human_input_v2/im_provider/**/*.py`、`api/core/helper/ssrf_proxy.py`、`api/pyproject.toml` 和 `api/uv.lock`。验证开始与结束时均得到相同 SHA-256：

```text
9de1ec06a3c5e00aee34639dbbb8511a292c4d158be38c58e7efbaa75d808ba7
```

生成命令：

```bash
{ find api/core/human_input_v2/im_provider -type f -name '*.py' -print; printf '%s\n' api/core/helper/ssrf_proxy.py api/pyproject.toml api/uv.lock; } \
  | LC_ALL=C sort \
  | xargs shasum -a 256 \
  | shasum -a 256
```

## Suite results

| suite | result |
| --- | --- |
| Immutable Provider JSON runtime and typing laws | 234 passed, 3 warnings |
| Immutable Provider JSON static checks | mypy passed; Pyrefly completed with 1 redundant-cast warning |
| Provider event consumer regressions | 8 passed, 15 warnings |
| Personal destination failure regressions | 15 passed, 5 warnings |
| Unit, complete `human_input_v2` plus `ssrf_proxy` | 974 passed, 13 warnings |
| Integration, complete `human_input_v2` directory | 234 passed, 15 warnings |
| Evidence matrix validation | 22 passed, 3 warnings |

最终 unit coverage 命令同时执行完整 unit suite：

```bash
COVERAGE_FILE=/tmp/.coverage-dify-im-unit-personal-final-20260803 \
uv run --project api --locked pytest \
  -o 'addopts=--import-mode=importlib' \
  -q api/tests/unit_tests/core/human_input_v2 \
  api/tests/unit_tests/core/helper/test_ssrf_proxy.py \
  --cov=core.human_input_v2.im_provider \
  --cov=core.helper.ssrf_proxy \
  --cov-branch \
  --cov-report=json:/tmp/dify-im-unit-coverage-personal-final-20260803.json
```

最终 integration coverage 命令同时执行完整 integration suite：

```bash
COVERAGE_FILE=/tmp/.coverage-dify-im-integration-personal-fixed-20260803 \
uv run --project api --locked pytest \
  -o 'addopts=--import-mode=importlib' \
  -q api/tests/integration_tests/core/human_input_v2 \
  --cov=core.human_input_v2.im_provider \
  --cov=core.helper.ssrf_proxy \
  --cov-branch \
  --cov-report=json:/tmp/dify-im-integration-coverage-personal-fixed-20260803.json
```

## Line and branch coverage

Denominator 固定为 14 个 production 文件：全部 `api/core/human_input_v2/im_provider/**/*.py` 加 `api/core/helper/ssrf_proxy.py`。Line threshold 独立判定为 unit ≥95%、integration ≥90%；branch 仅单独报告，不与 line numerator 混合。

| suite | files | covered lines | total lines | line percent | covered branches | total branches | branch percent |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Unit | 14 | 3570 | 3714 | 96.1228% | 935 | 1034 | 90.4255% |
| Integration | 14 | 3344 | 3714 | 90.0377% | 771 | 1034 | 74.5648% |

personal-user-only 迁移后的第一次完整 integration selection 得到 `3335/3714`（89.7954%），低于 90%
threshold。Coverage JSON 将缺口定位到 personal destination 的 Provider-specific failure mappings；随后只在
integration tests 中补齐 Slack `users.info` missing-scope、Microsoft Teams exact member malformed/mismatch，以及
WeCom exact user malformed/incomplete response。15 个 targeted regressions 通过后，使用全新的隔离 coverage data
file 重新执行完整 integration selection，得到表中的最终 `3344/3714`。该修复未修改 production。

聚合命令对 unit 与 integration JSON 使用相同公式：

```bash
for coverage_json in \
  /tmp/dify-im-unit-coverage-personal-final-20260803.json \
  /tmp/dify-im-integration-coverage-personal-fixed-20260803.json
do
jq -r '
  [.files | to_entries[]
    | select(.key | test("(^|/)core/human_input_v2/im_provider/.*\\.py$|(^|/)core/helper/ssrf_proxy\\.py$"))
    | .value.summary]
  | {
      files: length,
      covered_lines: (map(.covered_lines) | add),
      total_lines: (map(.num_statements) | add),
      covered_branches: (map(.covered_branches) | add),
      total_branches: (map(.num_branches) | add)
    }
  | [.files, .covered_lines, .total_lines, (.covered_lines / .total_lines * 100),
     .covered_branches, .total_branches, (.covered_branches / .total_branches * 100)]
  | @tsv
' "$coverage_json"
done
```

## Additional verification commands

```bash
uv run --project api --locked pytest \
  -o 'addopts=--import-mode=importlib' \
  -q api/tests/unit_tests/core/human_input_v2/test_im_provider_immutable_json.py

uv run --project api --locked pytest \
  -o 'addopts=--import-mode=importlib' \
  -q api/tests/unit_tests/core/human_input_v2/test_im_provider_immutable_json_typing.py

uv run --project api --locked pytest \
  -o 'addopts=--import-mode=importlib' \
  -q \
  api/tests/integration_tests/core/human_input_v2/test_slack_im_provider_integration.py::test_slack_block_action_authentication_and_sink_ack_mapping_use_the_concrete_context \
  api/tests/integration_tests/core/human_input_v2/test_slack_im_provider_stream_integration.py::test_slack_stream_pinned_sdk_routes_wire_event_and_owns_ack \
  api/tests/integration_tests/core/human_input_v2/test_feishu_lark_im_provider_stream_integration.py::test_feishu_stream_pinned_sdk_routes_protobuf_event_and_owns_ack \
  api/tests/integration_tests/core/human_input_v2/test_feishu_lark_im_provider_webhook_integration.py::test_feishu_lark_plaintext_webhook_preserves_nested_payload_without_synthesizing_identity

uv run --directory api --dev pyrefly check \
  --summary=none \
  --use-ignore-files=false \
  --disable-project-excludes-heuristics=true \
  --project-excludes=.venv \
  --project-excludes=migrations/ \
  tests/unit_tests/core/human_input_v2/test_im_provider_immutable_json.py

uv --directory api run mypy \
  --exclude-gitignore \
  --check-untyped-defs \
  --disable-error-code=import-untyped \
  tests/unit_tests/core/human_input_v2/test_im_provider_immutable_json.py

uv run --project api ruff format --check \
  api/core/human_input_v2/im_provider \
  api/tests/unit_tests/core/human_input_v2/test_*im_provider*.py \
  api/tests/integration_tests/core/human_input_v2 \
  api/core/helper/ssrf_proxy.py \
  api/tests/unit_tests/core/helper/test_ssrf_proxy.py

uv run --project api ruff check \
  api/core/human_input_v2/im_provider \
  api/tests/unit_tests/core/human_input_v2/test_*im_provider*.py \
  api/tests/integration_tests/core/human_input_v2 \
  api/core/helper/ssrf_proxy.py \
  api/tests/unit_tests/core/helper/test_ssrf_proxy.py

git diff --check

./dev/pyrefly-check-local \
  api/core/human_input_v2/im_provider \
  api/core/helper/ssrf_proxy.py

uv --directory api run mypy \
  --exclude-gitignore \
  --exclude '(^|/)conftest\.py$' \
  --exclude 'tests/' \
  --exclude 'migrations/' \
  --exclude 'dev/generate_swagger_specs.py' \
  --exclude 'dev/generate_fastopenapi_specs.py' \
  --check-untyped-defs \
  --disable-error-code=import-untyped \
  core/human_input_v2/im_provider \
  core/helper/ssrf_proxy.py

uv lock --check --project api

uv run --project api python -c 'from importlib.metadata import version; expected = {"lark-oapi": "1.7.1", "slack-sdk": "3.43.0"}; actual = {name: version(name) for name in expected}; assert actual == expected, (actual, expected); print(actual)'

uv run --project api python -c 'import tomllib; packages = {package["name"]: package["version"] for package in tomllib.load(open("api/uv.lock", "rb"))["package"]}; forbidden = {"alibabacloud-dingtalk", "dingtalk-stream"}; assert packages.keys().isdisjoint(forbidden), packages.keys() & forbidden; print(len(packages))'

openspec validate define-im-provider-adapter-contracts --strict

uv run --project api pytest \
  -o 'addopts=--import-mode=importlib' \
  -q api/tests/unit_tests/core/human_input_v2/test_im_provider_evidence_matrix_validation.py
```

以上 gates 均完成。Immutable Provider JSON runtime/typing laws、Provider event consumer regressions、完整 scoped
source 的 Pyrefly、mypy、Ruff 与测试通过；immutable JSON 的 focused Pyrefly check 仅报告一条 redundant-cast
warning，mypy 未报告问题。Lockfile 解析 520 个 packages，
保留 `lark-oapi==1.7.1` 与 `slack-sdk==3.43.0`，且 locked graph 不包含 `dingtalk-stream` 或
`alibabacloud-dingtalk`；OpenSpec strict validation 为 valid。

## Final scope and safety gates

验证前后的 production content fingerprint 均为
`9de1ec06a3c5e00aee34639dbbb8511a292c4d158be38c58e7efbaa75d808ba7`。`git diff --check` 通过；
`openspec/changes/define-im-provider-adapter-contracts/tasks.md` 的 SHA-256 在 tester GREEN 轮次前后均为
`8e86858b8f70bf435e4a809018bd2b6737e306b31d3a5f8e27d489f1017c85fe`。本轮没有勾选或修改 tasks。

Evidence fixtures 的敏感字段扫描未发现未脱敏的 access token、refresh token、client/app/corp/signing secret 或
authorization value；private-key PEM、Slack token pattern 与 OpenAI-style secret pattern 扫描同样无匹配。
Evidence validator 的 repository-reference、fixture digest、redaction 和 conservative roll-up gates 全部通过。

共享 `api/.venv` 仍可观察到一个 extraneous `dingtalk-stream` distribution。它不属于 `api/pyproject.toml`、`api/uv.lock` 或 locked graph，本次验证未通过修改共享环境来掩盖该污染；依赖闭包结论仅基于声明文件、lockfile 与 `--locked` 执行。

## Matrix status after verification

Evidence matrix 同时保留两个独立 accounting level：34 行 aggregate Provider-operation capability matrix，以及 76 行 exact `(provider, operation, external_entry, condition)` inventory。两层描述同一组能力的不同粒度，不能相加为一个“总缺口”；下表分别报告每层自身 evidence cells 的 `MISSING` 数量。

Aggregate capability matrix（34 rows，170 evidence cells）：

| column | MISSING |
| --- | ---: |
| unit_test | 0 |
| integration_test | 0 |
| real_execution | 22 |
| sanitized_fixture | 22 |
| independent_crypto | 4 |

Exact External Entry Inventory（76 rows，380 evidence cells）：

| column | MISSING |
| --- | ---: |
| unit_test | 0 |
| integration_test | 0 |
| real_execution | 36 |
| sanitized_fixture | 36 |
| independent_crypto | 4 |

Exact `MISSING` 按 Provider 与 actionability 分组如下；`unit_test` / `integration_test` 属于本地 executable evidence，`real_execution` / `sanitized_fixture` 需要授权的非生产 Provider 执行与留存，`independent_crypto` 需要独立于 adapter 的 test-only 生成器或验证器：

| provider | exact rows | unit_test | integration_test | real_execution | sanitized_fixture | independent_crypto |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Slack | 10 | 0 | 0 | 6 | 6 | 1 |
| Feishu/Lark | 24 | 0 | 0 | 6 | 6 | 2 |
| DingTalk | 12 | 0 | 0 | 4 | 4 | 0 |
| WeCom | 14 | 0 | 0 | 7 | 7 | 0 |
| Microsoft Teams | 16 | 0 | 0 | 13 | 13 | 1 |

Validation gate 对 76 个 exact identity keys 执行 exact equality，并逐 entry 强制 evidence schema、状态格式、repository reference 实存以及 `N/A` 适用性。Aggregate cells 是 exact entries 的 conservative roll-up：任一 exact entry 为 `MISSING` 时 aggregate 同轴必须保持 `MISSING`；只有全部 exact entries 均为 `N/A` 时 aggregate 才能使用 `N/A`。Tasks 7.1–7.5 任一开始勾选后，completion gate 会同时扫描 aggregate 与 exact 两层并拒绝任何残留 `MISSING`。Feishu Phase A partial fixture 闭合 destination 的 cold-token 与三个成功 identity branches，以及 text/card-send/card-update 的全部 exact entries；实际不可达的 Email destination、未观察到的 Directory department branches 与相关 aggregate cells继续保持 `MISSING`。WeCom 与 Microsoft Teams Directory partial fixtures 只闭合各自明确观察到的 token exact entry。Microsoft Teams credential testing 只执行 tenant-scoped client-credentials exchange，不再维护业务未使用的 organization lookup inventory row。DingTalk Directory token fixture 结合既有 probes/traversal evidence 闭合 Directory aggregate 两轴；DingTalk 与 WeCom 的 removed Webhook/STREAM scope 不保留 inventory row。Slack channel-targeted messaging/card/update 与由该 channel card 触发的 Socket `block_actions` capture 均标记为 obsolete historical evidence，不能关闭 personal-user-only rows。Historical Events API attempt 与 Slash command inspection 均继续明确标记为 out of scope；它们没有被用于补齐未实现的 Events API/slash-command entry。
