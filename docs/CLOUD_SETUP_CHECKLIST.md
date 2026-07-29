# 云与第三方账号设置清单

## Google Cloud

- OAuth Consent Screen；
- Gmail 只读 Scope 与单独发送 Scope；
- Pub/Sub Topic、Subscription 和 Gmail watch 权限；
- 正式 HTTPS Callback；
- Token 撤销测试；
- historyId 过期恢复演练。

## Microsoft Entra

- 应用注册；
- Mail.Read 与 Mail.Send 分离授权；
- 正式 Redirect URI；
- Graph webhook 公网 URL；
- clientState；
- subscription 续订；
- 文件夹级 deltaLink 恢复。

## 云基础设施

- 托管 PostgreSQL 16；
- Point-in-time recovery；
- S3 兼容对象存储；
- Secrets Manager；
- TLS 证书；
- 集中日志与告警；
- 私有网络和出站控制；
- 独立 staging / production。

每个完成项都应上传配置截图、测试记录或供应商结果作为 Gate Evidence，不能只在文档中打勾。
