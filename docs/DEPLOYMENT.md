# Production Pilot 部署

## 环境

- local：SQLite、local_headers、filesystem、deterministic model、禁止 live send；
- staging：PostgreSQL、JWT/OIDC、测试 OAuth、S3、默认禁止 live send；
- production：独立 PostgreSQL/S3/Secrets/OAuth/模型账号，Pilot Gate enforcement 开启。

## Production 必需配置

```text
WORKBUDDY_ENVIRONMENT=production
WORKBUDDY_DATABASE_URL=postgresql+psycopg://...
WORKBUDDY_PUBLIC_BASE_URL=https://workbuddy.example.com
WORKBUDDY_AUTH_MODE=oidc
WORKBUDDY_AUTH_OIDC_ISSUER=...
WORKBUDDY_AUTH_OIDC_AUDIENCE=...
WORKBUDDY_AUTH_JWKS_URL=...
WORKBUDDY_TOKEN_ENCRYPTION_KEY=...
WORKBUDDY_OBJECT_STORE_PROVIDER=s3
WORKBUDDY_OBJECT_STORE_BUCKET=...
WORKBUDDY_BACKUP_BUCKET=...
WORKBUDDY_ALERT_WEBHOOK_URL=...
WORKBUDDY_REQUIRE_PILOT_FOR_LIVE_SEND=true
```

## Kubernetes

1. 将 `deploy/k8s/secret.example.yaml` 转换为 Secrets Manager/External Secrets；
2. 修改镜像和域名；
3. 先执行 migration Job；
4. `kubectl apply -k deploy/k8s`；
5. 配置 Prometheus 抓取 `/metrics/prometheus`；
6. 导入 `deploy/monitoring/prometheus-alerts.yaml`。

NetworkPolicy 是最小基线。实际集群应将出站 443 限制到组织代理或明确 Provider CIDR/域名出口。

## 发布顺序

1. 数据库快照；
2. Alembic migration；
3. API canary；
4. Worker；
5. `/health/ready`；
6. `scripts/smoke_staging.sh`；
7. `scripts/load_test.py`；
8. 仅在 Gate B/C Ready 后登记 LIVE_SEND 试点邮箱；
9. Gate D 演练后再次签署。

## 备份恢复

```bash
./scripts/backup_postgres.sh
./scripts/restore_postgres.sh var/backups/FILE.dump
```

恢复必须在隔离环境演练，验证 SHA-256、Alembic current、审计链和 Mission 数量。

## Commercial GA additions

Production Commercial GA should additionally configure:

```bash
WORKBUDDY_COMMERCIAL_PRICING_APPROVED=false
WORKBUDDY_BILLING_PROVIDER=manual
WORKBUDDY_BILLING_WEBHOOK_SECRET=<secret after a provider is selected>
```

Do not set commercial pricing approved until the price catalog, contracts, tax handling and billing operations have been formally approved. Migration `0010_commercial_ga` must be applied before enabling the commercial routes.
