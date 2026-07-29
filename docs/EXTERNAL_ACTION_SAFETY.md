# 外部动作安全模型

## 不变量

1. Draft/Artifact 生命周期与 ExternalOperation 生命周期分离；
2. 老板审批绑定精确动作内容哈希和 Mission 版本；
3. 收件人、正文、附件或关键参数变化后审批失效；
4. 操作使用唯一 `operation_key`；
5. 每次 Provider 调用生成 OperationAttempt；
6. 真实发送必须在执行前再次运行策略校验；
7. Provider 接收不等于成功，必须核验；
8. `UNKNOWN` 禁止直接重试；
9. 网络传输异常、5xx 或 Provider 接收后无法核验均视为结果不确定并持久化为 `UNKNOWN`；
10. Gmail 只有重新读取到带 `SENT` 标签的消息才算核验成功。

## 真实发送双重许可

部署层与租户层都必须允许：

- Feature Flag；
- 收件人地址/域名白名单；
- BCC；
- 附件；
- 每日限额；
- 单 Mission 限额。

采用更严格的限制。任一层不允许即阻断。

## 状态机

```text
PREPARED → POLICY_REVIEWED → APPROVED → EXECUTING → VERIFYING → SUCCEEDED
                                               ├→ FAILED
                                               └→ UNKNOWN
```

`UNKNOWN` 后只能核验为成功或失败。需要重新发送时创建新的审批（如内容变化）和新的 ExternalOperation。
