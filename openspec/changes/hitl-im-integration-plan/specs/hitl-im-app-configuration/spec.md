## ADDED Requirements

### Requirement: IM app config supports edition-specific resolution
系统 SHALL 通过 resolver 按部署版本解析 IM app config，并支持企业自建与 ISV 安装两类 install mode。

#### Scenario: CE resolves deployment global self-built app
- **WHEN** CE 部署发送 IM 消息
- **THEN** 系统 SHALL 使用 deployment global 的 self-built app config

#### Scenario: EE resolves tenant override before deployment global
- **WHEN** EE 部署发送 IM 消息
- **THEN** 系统 SHALL 优先使用 tenant override self-built app config，并在缺失时 fallback 到 deployment global self-built app config

#### Scenario: Cloud resolves required first-phase providers
- **WHEN** Cloud tenant 使用 Slack 或钉钉 IM
- **THEN** 系统 SHALL 支持 Slack ISV install 和钉钉 tenant self-built app config

### Requirement: Self-built app credentials are validated
系统 SHALL 在使用企业自建 IM app 前校验所需 credentials。

#### Scenario: Self-built config is missing credentials
- **WHEN** provider adapter 请求缺失必要 credential 的 self-built app config
- **THEN** 系统 SHALL 拒绝发送或 callback 处理，并记录可排障错误

#### Scenario: Feishu demo requires long connection mode
- **WHEN** phase-1 demo 使用飞书企业自建应用
- **THEN** 系统 SHALL 要求配置为 long connection 模式，而 SHALL NOT 把 webhook 模式视为 demo-ready configuration

### Requirement: ISV install lifecycle is tracked
系统 SHALL 跟踪 ISV install、uninstall、token refresh 和 token rotation 状态。

#### Scenario: Slack team is installed
- **WHEN** Cloud tenant 完成 Slack ISV install
- **THEN** 系统 SHALL 将该 Dify tenant 关联到一个 Slack team id，并保存 token refresh 所需状态

#### Scenario: ISV app is uninstalled
- **WHEN** provider 通知 app uninstall
- **THEN** 系统 SHALL 标记 install inactive，并 SHALL NOT 使用该 install 发送后续 HITL IM 消息

### Requirement: Provider model allows future install modes
系统 SHALL 在 provider config resolver 和 binding credential scope 中预留同一 provider 后续支持 ISV 和 self-built 的空间。

#### Scenario: Future provider adds ISV support
- **WHEN** 一个已有 self-built provider 后续新增 ISV install mode
- **THEN** 系统 SHALL 能通过新增 config source 或 install row 支持，而不要求迁移已有 HITL recipient 或 binding 数据

### Requirement: App context exposes stable credential scope
系统 SHALL 将解析后的 IM app config 表达为稳定的 runtime app context，而不是要求所有配置都必须有 DB installation row。

#### Scenario: Deployment global config is resolved
- **WHEN** CE 或 EE 使用 deployment global self-built app config
- **THEN** resolver SHALL 返回 provider、install mode、scope type、scope id、provider workspace id 和 credentials

#### Scenario: Stateful install is resolved
- **WHEN** Cloud Slack ISV install 被用于发送或 callback 校验
- **THEN** resolver SHALL 从持久化 install 状态返回相同的 credential scope 和 token lifecycle 信息
