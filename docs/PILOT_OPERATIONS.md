# Production Pilot 操作流程

## 一、操作流程

### 1. 创建试点

```bash
PYTHONPATH=src python scripts/pilot_bootstrap.py --activate
```

### 2. 登记邮箱

- `SHADOW`：只同步与调度评估；
- `AGENT_DRAFT`：允许 Agent 执行和内部成果；
- `LIVE_SEND`：只用于 Gate D 受控演练。

Mailbox mode 不是单独的权限。真实发送仍需全局 Feature Flag、双白名单、审批、限额和 Pilot Gate enforcement。

> 邮箱模式（`SHADOW` / `AGENT_DRAFT` / `LIVE_SEND`）与客户上线状态机的阶段同名，参见 [CUSTOMER_ONBOARDING.md](CUSTOMER_ONBOARDING.md)。

### 3. 证据

通过 UI、API 或：

```bash
PYTHONPATH=src python scripts/submit_gate_evidence.py PROGRAM B cursor_recovery_drill --metrics @result.json
```

提交后必须由责任人验证。上传文件由对象存储保存并记录哈希。

### 4. 签署

责任人 Token 必须带对应 Role。签署后新增证据会改变快照并自动使旧签署失效。

### 5. 事故

P0/P1 自动阻断 Production Go/No-Go。解决事故必须保存 resolution，并生成审计事件。

### 6. 报告

```bash
PYTHONPATH=src python scripts/generate_go_no_go.py PROGRAM_ID
```

`GO` 返回 0；`NO_GO` 返回 3。

## 二、日常检查清单

### 每日检查

1. `/health/ready` 无阻断；
2. `/v1/ops/status` 无 `UNKNOWN`、Outbox 积压和 P0/P1；
3. Gmail watch / Graph subscription 未临近到期；
4. 同步失败已分配负责人；
5. 当日发送量未接近限额；
6. 调度纠正和 Agent 返工完成抽查；
7. 新证据由独立责任人验证。

### 每周检查

- 三个专家团质量指标；
- Skill 版本和失败案例；
- 模型成本、延迟和供应商变化；
- 权限与白名单；
- P2/P3 事故趋势；
- 备份可用性；
- Gate 状态和证据快照。

## 三、扩量与停止条件

### 扩量顺序

1. Shadow：同步和调度建议；
2. Agent Draft：允许 Agent 执行，但只产生内部成果；
3. Live Send：仅对白名单收件人逐封审批发送。

不得跨级扩量。扩量阶段对应客户上线的 Shadow / Agent Draft / Live Send 阶段，参见 [CUSTOMER_ONBOARDING.md](CUSTOMER_ONBOARDING.md)。

### 立即停止条件

- 跨租户或跨客户数据；
- 未审批外部写操作；
- 重复发送；
- 审批内容与实际动作不一致；
- 权限无法撤销；
- 审计链损坏；
- 无法恢复的 Mission；
- 高风险漏报。

发生以上情况：暂停公司外部写操作，登记 P0/P1，保存证据，按 Incident Runbook 处理。
