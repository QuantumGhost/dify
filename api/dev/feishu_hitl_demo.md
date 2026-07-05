# Feishu HITL Demo Guide

本文档说明 CE Demo 范围内的飞书 HITL 集成如何配置与验证。当前实现默认复用现有 HITL `member` recipient 配置，不提供 Contact UI，也不提供 member contact 的手工创建、编辑、删除入口。

## 1. 必要配置

至少需要配置以下环境变量：

```bash
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_OAUTH_SCOPES=contact:user.base:readonly
FEISHU_OAUTH_REDIRECT_PATH=/console/api/oauth/feishu-im/callback
CONSOLE_API_URL=http://localhost:5001
CONSOLE_WEB_URL=http://localhost:3000
APP_WEB_URL=http://localhost:3000
```

说明：

- `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 同时用于账号绑定、IM 发卡、长连接 callback listener。
- 飞书开发者后台需要把 `CONSOLE_API_URL + FEISHU_OAUTH_REDIRECT_PATH` 加入 Redirect URL 白名单。
- 飞书应用需要具备机器人能力，并启用卡片回调的长连接接收方式。

## 2. 初始化 member contacts

当前实现只支持通过脚本把 workspace members 导入为 Demo-scope member contacts：

```bash
uv run --project api flask import-member-contacts --tenant-id <tenant-id>
```

行为说明：

- 导入命令会按 `tenant_id + account_id` upsert。
- 已存在 contact 会同步最新的 `name` 和 `email`。
- 未导入的 member 仍可保留 email 路径，但不会获得稳定的 contact 投影。

## 3. 账号绑定飞书

当前登录账号可通过以下入口发起绑定：

```text
/console/api/oauth/feishu-im/bind
```

绑定完成后：

- 账号级 `AccountIntegrate(provider="feishu_im")` 会写入或刷新。
- member contact 在运行时通过 `account_id` 投影读取该绑定结果。

## 4. 启动长连接 listener

飞书卡片回调不复用 Web worker 进程，需要单独启动 listener：

```bash
uv run --project api flask run-feishu-hitl-listener
```

说明：

- listener 使用 `lark.ws.Client` 长连接模式接收 `card.action.trigger`。
- 同一个应用最多建立 50 个连接，重复启动前应确认旧 listener 已退出。

## 5. Workflow Authoring Limits

当前卡片直填只强支持以下子集：

- `paragraph`
- `select`
- 最多两个动作按钮

当表单包含以下情况时，系统会自动退化为 IM link fallback，而不是发送半残卡片：

- `file`
- `file-list`
- 超过两个动作按钮
- 其他当前未支持的输入类型

退化后，飞书消息会给出独立 Web HITL 表单链接，真实提交仍走现有 recipient-token 路径。

## 6. 建议验证顺序

建议按以下顺序手工验证：

1. 先执行 `import-member-contacts`，确认目标审批人已导入。
2. 使用目标 Dify 账号访问 `/console/api/oauth/feishu-im/bind` 完成飞书绑定。
3. 启动 `run-feishu-hitl-listener`。
4. 在 workflow 中使用现有 `member` recipient 配置一个 HITL 节点。
5. 触发 workflow，确认已绑定成员收到 `IM + Email`，未绑定成员仍只有 Email。
6. 对仅含 `paragraph/select` 的表单，验证可直接在飞书卡片中提交并恢复执行。
7. 对含 `file/file-list` 的表单，验证飞书消息退化为 Web 链接，且 Web 提交后 workflow 继续执行。

## 7. 审计与排障

重点排查以下数据：

- `member_contacts`：确认 contact 是否已导入。
- `account_integrates`：确认 `provider=feishu_im` 是否存在。
- `human_input_feishu_deliveries`：确认 message 关联、发送状态、失败原因、完成状态。

如果 workflow 已恢复但飞书侧仍显示旧卡片，优先检查：

- listener 是否仍在运行。
- `human_input_feishu_deliveries.status` 是否已经更新为 `completed`。
- 当前卡片是否走的是 link fallback；该路径默认依赖幂等保护，而不是主动消息更新。
