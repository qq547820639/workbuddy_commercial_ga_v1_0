# 发布门证据系统

## 原则

发布门由三部分组成：

1. 系统自动观察；
2. 已验证的真实证据；
3. 对应责任人的签署。

三者全部满足时 Gate 才为 Ready。

## 证据生命周期

```text
提交 → PENDING → VERIFIED / REJECTED
```

证据可附加文件。文件写入对象存储，并记录 SHA-256、大小、类型和不可变引用。

## 签署失效

每次签署记录当前 Gate 下所有已验证证据的快照哈希。新增、替换或重新验证证据后，快照变化，旧签署不再计入 Gate。

## Gate B

自动观察：

- 至少一次成功邮箱同步；
- 至少一次人工调度复核；
- 连续稳定运行天数；
- 调度准确率达到试点目标。

证据：游标恢复、同步稳定、调度准确率、高风险召回率。

签署：Product Owner、IT Admin。

## Gate C

自动观察：真实模型调用与质量评估。

证据：模型数据协议、Agent 评估、红队测试、Evidence 覆盖率。

签署：Product Owner、AI Platform Owner、Security Owner、Business Owner。

## Gate D

自动观察：至少一次非 Demo、服务商核验成功的外部操作。

证据：真实发送核验、UNKNOWN 恢复、重复发送为零、未审批发送为零。

签署：Operations Owner、Security Owner、Product Owner。

## Production

自动要求 Gate B/C/D 全部 Ready，并且无未解决 P0/P1。

证据：渗透测试、隐私评审、备份恢复、事故响应、支持就绪。

签署：Product、Platform、Security、Privacy、Operations 五类负责人。
