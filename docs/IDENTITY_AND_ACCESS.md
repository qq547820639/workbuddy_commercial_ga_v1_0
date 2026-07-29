# 身份与访问控制

## 身份来源

`local_headers` 仅用于本地开发。生产环境必须使用：

- `WORKBUDDY_AUTH_MODE=oidc`，配置 Issuer、Audience 和 JWKS；或
- 经过组织批准的 JWT 验证密钥。

JWT 必须至少包含：

```json
{
  "sub": "user-id",
  "tenant_id": "tenant-uuid",
  "roles": ["product_owner"]
}
```

`X-Tenant-ID` 和 `X-Actor-ID` 在 JWT/OIDC 模式中不会覆盖 Token Claim。数据库查询同时应用 tenant context 与 PostgreSQL forced RLS。

## 责任人角色

- `product_owner`
- `platform_owner`
- `it_admin`
- `ai_platform_owner`
- `security_owner`
- `privacy_owner`
- `operations_owner`
- `business_owner`

Gate 签署接口要求 Token 中包含被签署的角色。签署保存 Actor、时间、决定和证据快照哈希。

## UI

当前 UI 支持在会话级保存 Bearer Token，不写入 localStorage。正式部署建议使用身份感知代理或组织 SSO，在反向代理层注入 Bearer Token。

## 密钥

- Token 加密密钥必须与 App Secret 分离；
- OAuth Token 只以加密形式保存；
- 模型、OAuth、数据库和对象存储密钥存于 Secrets Manager；
- 禁止在 ConfigMap、Git、日志和前端返回值中保存密钥。
