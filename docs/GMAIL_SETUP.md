# Gmail 设置

## 权限分离

只读试点连接使用 `gmail.readonly`。真实发送必须让用户重新授权并单独增加 `gmail.send`。连接只读邮箱不代表它可以发送。

## 配置步骤

1. 在 Google Cloud 建立独立的 staging OAuth 应用；
2. 配置授权回调：`/v1/connectors/gmail/callback`；
3. 如启用实时通知，建立 Pub/Sub Topic 和 push Subscription；
4. 允许 Gmail 服务向 Topic 发布；
5. 配置环境变量：

```text
WORKBUDDY_GMAIL_CLIENT_ID
WORKBUDDY_GMAIL_CLIENT_SECRET
WORKBUDDY_GMAIL_REDIRECT_URI
WORKBUDDY_GMAIL_TOPIC_NAME
WORKBUDDY_GMAIL_PUBSUB_VERIFICATION_TOKEN
```

## 运行流程

- OAuth 后保存加密 refresh token；
- 初始同步读取最近邮件；
- Pub/Sub 通知只触发增量同步；
- 实际变化通过 Gmail History API 获取；
- 保存最新 history ID；
- history cursor 失效时进入 `RESYNC_REQUIRED`，执行受控重新同步；
- Worker 在 watch 临近到期时续订。

## 验收用例

- 重复通知不创建重复邮件；
- 通知乱序不破坏最终状态；
- cursor 失效可以恢复；
- 撤销 OAuth 后同步停止；
- 只读 scope 无法发送；
- 发送 scope + Feature Flag + 双白名单 + 审批全部满足后才可发送；
- Provider 接收后保存 message ID，并重新读取消息；只有消息带有 `SENT` 标签才视为核验成功；
- 网络不确定时进入 `UNKNOWN`，不自动重发。

## Webhook 租户路由

Pub/Sub 请求不携带 WorkBuddy 租户头。系统先使用不含邮件内容和凭据的 `WebhookBinding` 按邮箱地址找到租户和账号，再切换到该租户的 forced-RLS 上下文。未知绑定会被安全忽略，重复 `messageId` 会被去重。
