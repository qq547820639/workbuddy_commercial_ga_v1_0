# WorkBuddy 发布门

WorkBuddy 的发布门分为两层：Production Pilot 门（A/B/C/D/Production Open）保证执行层可在真实生产环境安全运行；商用门（Commercial/Value/GA）在 Pilot GO 之上证明可正式签约、收费与扩量。两层都建立在同一套证据系统之上。

## 一、证据系统机制

### 原则

发布门由三部分组成：

1. 系统自动观察；
2. 已验证的真实证据；
3. 对应责任人的签署。

三者全部满足时 Gate 才为 Ready。

### 证据生命周期

```text
提交 → PENDING → VERIFIED / REJECTED
```

证据可附加文件。文件写入对象存储，并记录 SHA-256、大小、类型和不可变引用。

### 签署失效

每次签署记录当前 Gate 下所有已验证证据的快照哈希。新增、替换或重新验证证据后，快照变化，旧签署不再计入 Gate。

## 二、Pilot 门（A/B/C/D/Production Open）

### Gate A — 代码与平台

本交付通过：状态机、RLS、Outbox、审计、Skill、AgentRun、模型网关、邮箱连接器、外部操作安全、Pilot Evidence 系统、JWT/OIDC 边界、对象存储适配和自动化测试。

### Gate B — 邮箱影子试点

由系统自动观察、四类已验证证据和 Product Owner / IT Admin 签署共同决定。配置 OAuth 不等于 Gate B 通过。

自动观察：

- 至少一次成功邮箱同步；
- 至少一次人工调度复核；
- 连续稳定运行天数；
- 调度准确率达到试点目标。

证据：游标恢复、同步稳定、调度准确率、高风险召回率。

签署：Product Owner、IT Admin。

### Gate C — 模型与 Agent 执行

要求真实模型调用、质量评估、模型数据协议、业务评估、红队报告、Evidence 覆盖率，以及四类责任人签署。

自动观察：真实模型调用与质量评估。

证据：模型数据协议、Agent 评估、红队测试、Evidence 覆盖率。

签署：Product Owner、AI Platform Owner、Security Owner、Business Owner。

### Gate D — 受控真实发送

要求非 Demo 的 Provider 核验成功、UNKNOWN 演练、零重复/零未审批发送证据，以及 Operations、Security、Product 三方签署。

自动观察：至少一次非 Demo、服务商核验成功的外部操作。

证据：真实发送核验、UNKNOWN 恢复、重复发送为零、未审批发送为零。

签署：Operations Owner、Security Owner、Product Owner。

### Production Open

要求 Gate B/C/D Ready、无开放 P0/P1、五类生产证据和五类责任人签署。`generate_go_no_go.py` 只有在全部满足时返回 0。

自动要求 Gate B/C/D 全部 Ready，并且无未解决 P0/P1。

证据：渗透测试、隐私评审、备份恢复、事故响应、支持就绪。

签署：Product、Platform、Security、Privacy、Operations 五类负责人。

## 三、商用门（Commercial/Value/GA）

商用门在 Production Pilot GO 之上追加商用与组织证据。三个门均要求对应责任人签署，且签署仅对当前已验证证据快照有效；新增或替换证据会使先前签署失效。详见 [GA_RELEASE_GATES.md](GA_RELEASE_GATES.md)。

### Gate Commercial

证据：账单试算、上线演练、支持 SLA 演练、合规文件发布、租户退出演练。

签署角色：Product、Finance、Operations、Privacy 负责人。

### Gate Value

证据：设计伙伴结果、周活跃率、成果采用率、实测节省时间、试点转化率、单位经济。

签署角色：Product、Business、Finance 负责人。

### Gate GA

证据：Production Open GO、当前渗透测试、隐私/法律审批、连续 30 天无 P0/P1、支持与 On-call 就绪、已验证的客户退出。

签署角色：Product、Platform、Security、Privacy、Operations、Finance 负责人。

### 自动阻断条件

当出现以下任一情况时，GA 保持 `NO_GO`：

- 关联的 Production Pilot 未 GO；
- 没有处于试用或付费状态的订阅；
- 没有客户上线到达 Completed；
- 仍有 P0/P1 或重大事故未关闭；
- 必需的商用/合规文件未发布；
- 证据或责任人签署缺失。
