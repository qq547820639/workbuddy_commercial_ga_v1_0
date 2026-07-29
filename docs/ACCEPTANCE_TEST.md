# Production Pilot v0.4 验收

## 自动化

```bash
./scripts/verify.sh
```

覆盖：

- 41 项测试；
- 0001–0009 迁移；
- 多租户、状态机、UNKNOWN、Skill、工具和邮箱；
- Pilot Evidence、签署失效、事故阻断、对象存储；
- JWT Claim 覆盖伪造请求头；
- OpenAPI 和 UI 脚本；
- 黄金路径和诚实 NO_GO。

## 现场 Gate B

- 五天同步；
- Gmail/Graph cursor 恢复；
- 零漏件、零重复；
- 调度准确率与风险召回；
- Product/IT 签署。

## 现场 Gate C

- 真实模型；
- 100+ 脱敏案例/专家团；
- 红队；
- Evidence 100%；
- Product/AI/Security/Business 签署。

## 现场 Gate D

- LIVE_SEND 试点邮箱；
- Provider 核验；
- UNKNOWN 不重试；
- 重复/未审批发送为零；
- Operations/Security/Product 签署。

## Production

- 渗透、隐私、备份恢复、事故响应、支持就绪；
- B/C/D Ready；
- 无开放 P0/P1；
- 五方签署。
