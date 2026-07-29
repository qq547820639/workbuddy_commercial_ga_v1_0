# WorkBuddy 专家团操作系统 — Commercial GA v1.0

WorkBuddy 是建立在邮箱之上的 AI 数字公司操作系统：真人老板管理多个专家团，调度中心把邮件交给唯一主责团队，主理人规划 WorkItem，任务级 AgentRun 调用冻结版本的 Skill，高风险动作经老板审批后才允许执行。

Commercial GA v1.0 在 Production Pilot v0.4 的安全执行内核之上补齐了商用平台层：组织成员、套餐与订阅、用量计量、账单草稿、客户上线、支持 SLA、服务状态、合规文件确认和证据化 GA 发布门。

## 商用版新增

- 参考套餐目录、试用订阅和受控付费激活；
- 模型调用、AgentRun、真实发送的自动用量计量；
- 幂等 UsageRecord、配额视图、超额计算和人民币分账单；
- 发票状态机，`PAID` 必须有支付引用或人工支付凭证；
- 组织成员邀请和角色更新，并受用户配额约束；
- 客户上线状态机：Discovery → Configuration → Shadow → Agent Draft → Live Send → Completed；
- 每阶段强制清单，不允许跳级；
- P0–P3 支持工单、首响 SLA 和服务状态事故；
- 版本化合规文件及与内容哈希绑定的租户接受记录；
- Commercial、Value、GA 三个证据门及责任人签署；
- 签署绑定证据快照，新增证据后原签署自动失效；
- GA Go/No-Go 同时检查 Production Pilot、订阅、上线、事故和合规文档；
- 新租户隔离式开通、租户退出导出和商用初始化 CLI；
- Commercial GA 运营控制台。

## 生产与商用缺口闭环

在商用平台层之上，一次性补齐了 12 项生产与商用缺口的代码自动化：

1. 正式价格审批工作流（绑定目录哈希，阻止未审批激活）；
2. 支付服务商抽象、税务引擎和 Webhook 验签；
3. Terraform IaC（GCP/Entra）和 Workload Identity Federation；
4. SSE-KMS 对象存储加密（S3/GCS）；
5. 模型供应商 DPA 校验和成本费率管理；
6. 实发安全检查和 UNKNOWN 恢复演练脚本；
7. 渗透测试报告追踪（GA 要求外部第三方且全部修复）；
8. 合规文件双角色法律审批（legal_owner + privacy_owner）；
9. On-call 排班、升级策略和 SLA 合规检查；
10. 设计伙伴档案和客户价值指标报告；
11. 30 天无 P0/P1 观察窗口（自动重置，GA 前必须完成）；
12. GA 签署 HMAC-SHA256 密码学签名和验签。

代码自动化已完成，但真实组织证据（云账号、合同、支付、法律审批、客户数据、签字）仍需组织提供。在证据齐备前系统保持 `NO_GO`。详见 [生产缺口](docs/PRODUCTION_GAPS.md)。

## 本地启动

```bash
cd workbuddy_commercial_ga_v1_0
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
./scripts/run_local.sh
```

打开 `http://localhost:8000`，进入“商用与 GA”。

## 初始化商用记录

```bash
PYTHONPATH=src python scripts/commercial_bootstrap.py
```

该命令只创建：

- 参考套餐；
- 14 天试用订阅；
- 客户上线项目；
- GA 发布计划。

它不会伪造合同、付款、法律批准、真实客户价值或生产证据。

## 商用常用命令

```bash
# 创建隔离租户（需数据库管理员权限）
PYTHONPATH=src python scripts/provision_tenant.py \
  --name 'Example Company' \
  --owner-email owner@example.com \
  --owner-name 'Example Owner'

# 生成当前周期账单草稿
PYTHONPATH=src python scripts/generate_invoice.py

# 评估 GA；NO_GO 时返回非零退出码
PYTHONPATH=src python scripts/ga_check.py

# 客户退出前导出商用与审计数据，不执行删除
PYTHONPATH=src python scripts/tenant_exit_export.py --output tenant-exit.json

# Gap-closure 运维脚本
PYTHONPATH=src python scripts/billing_dry_run.py        # 账单试算
PYTHONPATH=src python scripts/check_live_send_safety.py  # 实发安全检查
PYTHONPATH=src python scripts/unknown_recovery_drill.py  # UNKNOWN 恢复演练
PYTHONPATH=src python scripts/sla_check.py               # SLA 合规检查
PYTHONPATH=src python scripts/oncall_drill.py            # On-call 演练
PYTHONPATH=src python scripts/value_report.py            # 客户价值报告
PYTHONPATH=src python scripts/observation_check.py       # 观察窗口检查
PYTHONPATH=src python scripts/ga_signoff_bundle.py       # GA 签署包导出
```

## 完整验证

```bash
./scripts/verify.sh
```

验证包括：

- Python 编译；
- 全部自动化测试；
- Alembic 0001–0019 空库迁移；
- OpenAPI（133 个 `/v1` 路径）；
- 前端 JavaScript；
- 配置和部署 YAML；
- 专家团黄金路径；
- Production Pilot 门禁；
- 商用初始化、账单和退出导出；
- 诚实 GA `NO_GO`；
- 生产预检；
- Gap-closure 脚本、Terraform 模块、Prometheus 告警。

## 价格与付款的诚实边界

内置套餐金额是产品建模用的参考目录，默认带有：

```text
REFERENCE_ONLY_UNTIL_COMMERCIAL_APPROVAL
```

只有设置正式批准开关，并提供合同或支付系统确认引用，付费订阅才可进入 `ACTIVE`。发票不得仅凭按钮变成 `PAID`。

## 仍需实际组织完成

代码无法替组织完成：

- 正式价格批准和商业合同；
- 支付服务商开户、税务和发票资质；
- Google Cloud、Microsoft Entra、域名、TLS 和生产云资源；
- 模型供应商数据处理协议；
- 真实客户上线和价值指标；
- 法律文本定稿、隐私评审和律师签字；
- 渗透测试、On-call 和正式客户支持；
- Gate B/C/D/Production/Commercial/Value/GA 的真实证据及责任人签署。

没有这些真实证据时，GA 报告会保持 `NO_GO`。

## 关键文档

- [商用架构](docs/COMMERCIAL_ARCHITECTURE.md)
- [计费与计量](docs/BILLING_AND_METERING.md)
- [客户上线](docs/CUSTOMER_ONBOARDING.md)
- [支持 SLA](docs/SUPPORT_SLA.md)
- [合规和法律边界](docs/COMPLIANCE_AND_LEGAL.md)
- [GA 发布门](docs/GA_RELEASE_GATES.md)
- [租户开通与退出](docs/TENANT_PROVISIONING_AND_EXIT.md)
- [完成矩阵](docs/COMMERCIAL_COMPLETION_MATRIX.md)
- [生产缺口](docs/PRODUCTION_GAPS.md)
- [最终验证](docs/FINAL_VERIFICATION.md)
