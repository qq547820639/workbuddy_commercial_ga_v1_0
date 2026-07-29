# 事件响应手册

## P0：可能发生未授权发送或跨租户访问

1. 立即暂停公司级运行；
2. 关闭 `WORKBUDDY_ENABLE_LIVE_EMAIL_SEND`；
3. 撤销相关邮箱 OAuth Token；
4. 保存审计、OperationAttempt、Provider 响应和日志；
5. 查询影响租户、收件人和消息 ID；
6. 指定事故负责人；
7. 按法律和隐私流程通知；
8. 未完成根因分析前不得恢复真实发送。

## P1：ExternalOperation UNKNOWN

1. 不点击重试；
2. 使用 provider reference、Sent Items 和审计核验；
3. 核验成功则标记 succeeded；
4. 核验失败则标记 failed；
5. 仍无法判定时保持 UNKNOWN 并升级；
6. 确需再发时创建新的 ExternalOperation。

## P1：同步 cursor 失效

1. 将账号置为 `RESYNC_REQUIRED`；
2. 暂停该账号自动调度；
3. 从受控时间窗重新同步；
4. 依靠 provider message ID 去重；
5. 比较同步前后计数；
6. 恢复影子模式后观察。

## P2：模型质量下降

1. 暂停受影响 Workflow；
2. 固定模型和 Skill 版本；
3. 回放评估集；
4. 检查 Prompt、Schema、来源和工具返回；
5. 回滚到已知版本；
6. 不得通过放宽审批掩盖质量问题。
