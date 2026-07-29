# Production Pilot 操作流程

## 1. 创建试点

```bash
PYTHONPATH=src python scripts/pilot_bootstrap.py --activate
```

## 2. 登记邮箱

- `SHADOW`：只同步与调度评估；
- `AGENT_DRAFT`：允许 Agent 执行和内部成果；
- `LIVE_SEND`：只用于 Gate D 受控演练。

Mailbox mode 不是单独的权限。真实发送仍需全局 Feature Flag、双白名单、审批、限额和 Pilot Gate enforcement。

## 3. 证据

通过 UI、API 或：

```bash
PYTHONPATH=src python scripts/submit_gate_evidence.py PROGRAM B cursor_recovery_drill --metrics @result.json
```

提交后必须由责任人验证。上传文件由对象存储保存并记录哈希。

## 4. 签署

责任人 Token 必须带对应 Role。签署后新增证据会改变快照并自动使旧签署失效。

## 5. 事故

P0/P1 自动阻断 Production Go/No-Go。解决事故必须保存 resolution，并生成审计事件。

## 6. 报告

```bash
PYTHONPATH=src python scripts/generate_go_no_go.py PROGRAM_ID
```

`GO` 返回 0；`NO_GO` 返回 3。
