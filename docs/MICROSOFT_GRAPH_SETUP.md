# Microsoft Graph / Microsoft 365 设置

## 权限分离

只读连接请求 `Mail.Read`；真实发送需要用户单独授权 `Mail.Send`。建议 staging 和 production 使用不同的 Entra 应用注册。

## 环境变量

```text
WORKBUDDY_GRAPH_CLIENT_ID
WORKBUDDY_GRAPH_CLIENT_SECRET
WORKBUDDY_GRAPH_TENANT
WORKBUDDY_GRAPH_REDIRECT_URI
WORKBUDDY_GRAPH_WEBHOOK_CLIENT_STATE
```

## 同步设计

- 每个邮件文件夹保存独立 delta cursor；
- webhook 只作为“发生变化”的信号；
- delta query 是同步数据的来源；
- notification ID/内容哈希用于去重；
- subscription 到期前必须续订；
- 无效 delta token 触发受控重同步。

## 发送与核验

系统先创建草稿，再发送草稿。请求使用 Outlook immutable ID preference，使草稿移动到 Sent Items 后仍可用同一 ID 查询。发送是异步行为，因此核验会短暂重试；在时间窗内无法观察到 Sent Items 记录时，操作进入 `UNKNOWN`，不会直接再发。

## 验收用例

- Inbox 和 Sent Items cursor 彼此独立；
- 重复 webhook 不创建重复事件；
- `clientState` 不匹配时拒绝；
- 只读 scope 不能发送；
- 发送后能在 Sent Items 验证 `isDraft=false`；
- 验证超时进入 `UNKNOWN`；
- 运维人员核验后结束，若需再次尝试必须新建 ExternalOperation。

## Webhook 租户路由

Graph 通知先按 subscription ID 查询最小化 `WebhookBinding`，校验 `clientState` 哈希后才进入对应租户上下文。绑定不保存邮件正文或 OAuth Token。未知 subscription、错误 clientState 和重复通知分别被拒绝或去重。
