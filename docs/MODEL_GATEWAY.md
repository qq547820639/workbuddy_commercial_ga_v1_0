# Model Gateway

## 目的

业务服务不直接依赖单一模型 SDK。所有模型任务经过统一网关，以便执行 JSON Schema Draft 2020-12 校验、预算、审计、超时和 Provider 切换。错误类型、缺失字段和额外字段都会被拒绝。

## 支持任务

- `dispatch`：业务类型、风险和专家团建议；
- `mission_plan`：主理人任务清单；
- `agent_execute`：WorkItem 成果和 Evidence；
- `quality_review`：质量检查辅助；
- `approval_pack`：老板审批材料。

## Provider

- `deterministic`：离线、稳定、用于测试和演示；
- `openai`：Responses API 结构化输出适配器，需 API Key；请求设置 `store=false`。

## 每次调用记录

- tenant / Mission / WorkItem / AgentRun；
- task type；
- Provider 和模型；
- prompt/config 版本；
- 输入与输出哈希；
- 状态、错误、延迟；
- 输入/输出 Token；
-人民币分成本估算。

不保存隐式私人推理过程。业务成果只保存结构化输出、Evidence、来源和必要审计数据。

## 安全边界

模型不能：

- 授予自身 ToolGrant；
- 改变专家团章程；
- 删除强制审批节点；
- 把邮件正文当作系统指令；
- 直接执行外部动作；
- 绕过收件人白名单和限额。

## 失败处理

AgentRun 的模型调用失败时，ModelInvocation 以 `FAILED` 状态保留，临时 ToolGrant 被撤销，Run 经 `FAILED → CLOSED` 清理上下文，WorkItem 进入 `BLOCKED`。重新执行必须由主理人显式创建新的 AgentRun，不能复用失败上下文。
