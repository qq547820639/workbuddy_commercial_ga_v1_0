# Tasks

> **前置条件**：用户是飞书企业管理员，可创建自建应用并审批 OAuth scope。妙搭应用已创建（app_17b6an5g35n）。

## 阶段 A：多维表格核心域数据层

### Task 1: 设计并初始化核心域多维表格
- [x] SubTask 1.1: 设计 12 张表 schema（邮件归档/团队/智能体/任务/工作项/执行记录/审批请求/产物/证据/协作请求/运行日志/配置），字段映射 ORM 模型关键属性
- [ ] SubTask 1.2: 用 `lark-cli base` 或飞书多维表格 Web 界面创建 Base 和所有表+字段
- [x] SubTask 1.3: 预填团队数据（5 个专家团 from config/teams/*.yaml）和默认配置
- [x] SubTask 1.4: 预填智能体数据（每个团队的主理人 + 子角色 AgentProfile）
- [ ] SubTask 1.5: 验证表结构可查询可写入

## 阶段 B：邮件接入 + dispatch 派单

### Task 2: 飞书自建应用 OAuth + 事件订阅配置
- [ ] SubTask 2.1: 在飞书开放平台创建/配置自建应用，申请 scope
- [ ] SubTask 2.2: 配置事件订阅——订阅"邮件接收"事件，回调 URL 指向妙搭云函数 `on_mail_received`
- [ ] SubTask 2.3: 将 App ID / App Secret 写入妙搭应用环境变量
- [x] SubTask 2.4: 实现 `lib/feishu-oauth.js`：用 app_id + app_secret 换 user_access_token，缓存并自动 refresh

### Task 3: 实现邮件接收云函数
- [x] SubTask 3.1: 实现 `functions/on_mail_received.js`：接收飞书事件订阅回调，解析邮件元数据
- [x] SubTask 3.2: 邮件元数据写入多维表格"邮件归档"表（去重：message_id 已存在则跳过）
- [x] SubTask 3.3: 触发 dispatch 流程（调用 `lib/dispatch.js`）

### Task 4: 实现 dispatch 派单
- [x] SubTask 4.1: 实现 `lib/dispatch.js`：从多维表格读取专家团 routing_rules，对邮件文本评分筛选候选团队
- [x] SubTask 4.2: 调用 LLM API（传入邮件文本 + 候选团队 charter + dispatch schema），返回分类结果
- [x] SubTask 4.3: 创建 Mission 记录（多维表格"任务"表 + 飞书任务），状态=ROUTED
- [x] SubTask 4.4: 高风险邮件（risk_level=high/critical）自动创建飞书审批实例
- [x] SubTask 4.5: 识别 supporting_team_keys 时创建 CollaborationRequest 记录
- [x] SubTask 4.6: 发送 IM 通知到主理人（新任务到达）

## 阶段 C：任务执行

### Task 5: 实现主理人规划工作项
- [x] SubTask 5.1: 实现 `functions/plan_workitems.js`：主理人触发，调用 LLM planner 根据 workflow 生成 WorkItem 列表
- [x] SubTask 5.2: 每个 WorkItem 写入多维表格"工作项"表 + 飞书子任务
- [x] SubTask 5.3: 按 role 匹配 AgentProfile，绑定 assigned_agent_profile_id
- [x] SubTask 5.4: 绑定 SkillRelease（从多维表格"技能"表查询冻结版本）

### Task 6: 实现智能体执行 AgentRun
- [x] SubTask 6.1: 实现 `functions/execute_agent_run.js`：启动 AgentRun，状态=RUNNING
- [x] SubTask 6.2: 调用 LLM API（传入 mission/work_item/agent_profile/skill/source 上下文 + agent_output_schema）
- [x] SubTask 6.3: LLM 返回 artifact + evidence，写入多维表格"产物"和"证据"表
- [x] SubTask 6.4: AgentRun 状态=SUBMITTED，WorkItem 状态=SUBMITTED
- [x] SubTask 6.5: 记录 ModelInvocation（token 用量/成本）用于预算管控
- [x] SubTask 6.6: 异常处理：AgentRun FAILED，WorkItem BLOCKED，主理人需显式重试

## 阶段 D：审批交付

### Task 7: 实现飞书审批集成
- [x] SubTask 7.1: 实现 `lib/feishu-approval.js`：调飞书审批 API 创建审批实例
- [x] SubTask 7.2: 高风险操作触发审批，Mission 状态=APPROVAL_REQUIRED
- [x] SubTask 7.3: 实现 `functions/on_approval_callback.js`：接收飞书审批回调
- [x] SubTask 7.4: 审批通过 → Mission 状态=APPROVED → 执行外部操作
- [x] SubTask 7.5: 审批拒绝 → Mission 状态=BLOCKED → 通知主理人

### Task 8: 实现外部操作执行
- [x] SubTask 8.1: 实现 `lib/feishu-mail-send.js`：通过飞书邮箱 API 发送邮件
- [x] SubTask 8.2: 实现 `lib/feishu-im.js`：发送 IM 交互卡片通知
- [x] SubTask 8.3: 审批通过后执行外部操作（发邮件/IM通知），记录 ExternalOperation 审计日志
- [x] SubTask 8.4: 操作完成后 Mission 状态=ACTION_EXECUTING → VERIFYING

## 阶段 E：看板与工作区

### Task 9: 实现专家团看板页面
- [x] SubTask 9.1: 创建 `pages/dashboard.html`：展示全部 active 专家团卡片
- [x] SubTask 9.2: 每张卡片显示：团队名/主理人/进行中任务数/活跃 WorkItem 数/待审批数/最近状态时间
- [x] SubTask 9.3: 卡片点击跳转团队工作区
- [x] SubTask 9.4: 数据每 30 秒自动刷新

### Task 10: 实现专家团工作区页面
- [x] SubTask 10.1: 创建 `pages/team_workspace.html`：按团队维度聚合 Mission/WorkItem/AgentRun/成员/章程/Skill/协作
- [x] SubTask 10.2: Mission 列表（进行中/全部过滤），每个显示状态/目标/主理人/WorkItem 进度
- [x] SubTask 10.3: Mission 详情展开 WorkItem 和 AgentRun（显式区分长期成员 vs 执行实例）
- [x] SubTask 10.4: 主理人操作按钮：生成清单/启动执行/提交审批
- [x] SubTask 10.5: 协作请求区：显示收到的 CollaborationRequest，主理人可接受/拒绝
- [x] SubTask 10.6: 进行中数据每 15 秒自动刷新

### Task 11: 实现配置与日志页面
- [x] SubTask 11.1: 创建 `pages/config.html`：章程版本管理 + 配置项管理
- [x] SubTask 11.2: 创建 `pages/logs.html`：运行日志分页查看（log_level/message/created_at）
- [x] SubTask 11.3: 创建 `pages/archives.html`：邮件归档分页列表，支持搜索和详情

## 阶段 F：部署与验证

### Task 12: 部署到妙搭
- [x] SubTask 12.1: 代码推送到 sprint/default，用户手动上传到妙搭
- [ ] SubTask 12.2: 配置妙搭环境变量（FEISHU_APP_ID/SECRET、LLM_API_KEY、BASE_TOKEN 等）
- [ ] SubTask 12.3: 验证云函数能 require lib 并正常执行
- [ ] SubTask 12.4: 发布妙搭应用，设置可见范围为 tenant

### Task 13: 端到端验证
- [ ] SubTask 13.1: 飞书工作台点 WorkBuddy → OAuth 授权 → 进入看板
- [ ] SubTask 13.2: 发测试邮件到飞书邮箱 → 事件订阅触发 → dispatch 派单 → 看板出现新任务
- [ ] SubTask 13.3: 主理人点"生成清单" → WorkItem 创建 → 启动执行 → AgentRun 完成
- [ ] SubTask 13.4: 高风险操作 → 飞书审批 → 审批通过 → 外部操作执行 → 闭环
- [ ] SubTask 13.5: 协作请求：dispatch 识别 supporting team → 接收团队接受 → 回传 Artifact
- [ ] SubTask 13.6: 关浏览器/关电脑 → 邮件事件仍正常触发（妙搭云端常驻）

### Task 14: 废弃旧 Python 方案
- [ ] SubTask 14.1: 验证全部通过后，删除 `feishu/` 目录下 Python 脚本
- [ ] SubTask 14.2: 更新文档指向妙搭应用入口
- [ ] SubTask 14.3: `src/workbuddy/` 保持不动（现有系统不删）

# Task Dependencies

- Task 1（数据层）无依赖，最先执行
- Task 2（OAuth+事件订阅）无依赖，与 Task 1 并行
- Task 3（邮件接收）依赖 Task 1 + Task 2
- Task 4（dispatch）依赖 Task 3
- Task 5（规划工作项）依赖 Task 4
- Task 6（AgentRun）依赖 Task 5
- Task 7（审批）依赖 Task 6
- Task 8（外部操作）依赖 Task 7
- Task 9-11（看板/工作区/配置）依赖 Task 1-8 的后端 API，可并行开发
- Task 12（部署）依赖 Task 1-11
- Task 13（端到端）依赖 Task 12
- Task 14（废弃旧代码）依赖 Task 13

推荐顺序：
Task 1 ‖ Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8 → Task 9 ‖ Task 10 ‖ Task 11 → Task 12 → Task 13 → Task 14
