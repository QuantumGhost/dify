## 1. 基础配置与最小联系人模型

- [ ] 1.1 在 `api/pyproject.toml` 中引入飞书官方 SDK 与长连接 SDK，并补充锁文件
- [ ] 1.2 在 `api/configs/feature/__init__.py` 中增加 CE Demo 所需的飞书配置项
- [ ] 1.3 增加最小的 member-contact 持久化模型与迁移，使 workspace members 可以被导入为 Demo-scope contacts
- [ ] 1.4 新增导入命令或脚本，把当前 workspace members 导入为 member contacts，并明确本期不提供 contact 编辑入口

## 2. 飞书绑定

- [ ] 2.1 在 `api/libs/oauth.py` 中实现飞书 OAuth provider，支持授权 URL、换 token、获取用户身份
- [ ] 2.2 在 `api/controllers/console/auth/` 中新增飞书绑定入口与回调，完成 Dify account 的 `feishu_im` 绑定写入
- [ ] 2.3 让 member contact 可以通过 `account_id` 投影读取该飞书绑定状态
- [ ] 2.4 为飞书绑定流程补充测试，覆盖未配置、首次绑定、重复绑定、非法 state 等场景

## 3. HITL Contact/Recipient 兼容解析

- [ ] 3.1 在 HITL 通知路径中增加 `member recipient -> member contact` 的兼容解析层
- [ ] 3.2 保持现有 workflow 节点配置不变，只在运行时解释 `member recipient` 为 `member contact`
- [ ] 3.3 为 contact 解析补充测试，覆盖已导入成员、未导入成员、账号不匹配等场景

## 4. 飞书通知发送

- [ ] 4.1 实现飞书通知渲染器，支持 `paragraph`、`select`、确认/取消动作的 interactive card
- [ ] 4.2 为超出卡片能力的表单实现 IM link fallback，复用现有独立 Web HITL 表单链接
- [ ] 4.3 扩展现有通知链路，使已绑定 member contact 默认执行 `IM + Email` 双渠道，未绑定成员与其他 recipient 保持现有 email 行为
- [ ] 4.4 增加飞书 IM 投递审计记录，保存消息关联信息、状态和失败原因
- [ ] 4.5 为飞书发送、双渠道路由和 link fallback 补充测试

## 5. 长连接回调与恢复执行

- [ ] 5.1 在 `api/commands/` 中新增独立的飞书长连接 listener 启动命令
- [ ] 5.2 实现飞书交互事件处理：操作者身份解析、member recipient 定位、token 提交调用
- [ ] 5.3 对 interactive card 成功提交返回 readonly result card，并处理重复提交、过期表单、身份不匹配
- [ ] 5.4 对 link fallback 完成后的 Feishu 侧状态做关闭或幂等保护
- [ ] 5.5 为 listener 与恢复执行链路补充测试

## 6. Demo 验证与操作说明

- [ ] 6.1 增加 Demo 操作说明，覆盖飞书配置、script-based contact 导入、账号绑定、listener 启动、workflow authoring 限制
- [ ] 6.2 跑通最小验证集：member contact 导入、Dify 账号绑定飞书、IM 发卡、IM 填卡、回调恢复执行
