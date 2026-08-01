# Checklist

## 阶段 A：数据层
- [ ] 多维表格包含 12 张核心域表（邮件归档/团队/智能体/任务/工作项/执行记录/审批请求/产物/证据/协作请求/运行日志/配置）
- [ ] 5 个专家团数据已预填（customer_success / finance_ops / hr_people / operations_delivery / sales_growth）
- [ ] 每个团队的主理人和子角色 AgentProfile 已预填
- [ ] 表结构支持按字段过滤查询（如按 team_key 查任务）

## 阶段 B：邮件接入 + dispatch
- [ ] 飞书自建应用已申请 mail:user_mailbox:readonly / im:message:create_by_user / approval:approval:* scope
- [ ] 事件订阅已配置，回调 URL 指向妙搭云函数 on_mail_received
- [ ] OAuth 授权流程：用户点同意 → 获得 user_access_token → 无需 IMAP 密码
- [ ] 新邮件到达 → 秒级触发事件订阅 → 妙搭云函数收到回调
- [ ] 邮件元数据写入多维表格"邮件归档"表（message_id 去重）
- [ ] dispatch 调 LLM 分类 → 返回 primary_team_key / risk_level / confidence
- [ ] Mission 创建 → 多维表格"任务"表 + 飞书任务
- [ ] 高风险邮件自动触发飞书审批
- [ ] supporting_team_keys 非空时创建 CollaborationRequest

## 阶段 C：任务执行
- [ ] 主理人点"生成清单" → LLM planner 生成 WorkItem 列表
- [ ] WorkItem 写入多维表格 + 飞书子任务
- [ ] WorkItem 绑定 assigned_agent_profile_id（按 role 匹配）
- [ ] WorkItem 绑定 skill_release_id（冻结版本 Skill）
- [ ] 启动 AgentRun → 调 LLM → 返回 artifact + evidence
- [ ] AgentRun 状态 RUNNING → SUBMITTED
- [ ] WorkItem 状态 ASSIGNED → SUBMITTED
- [ ] 产物和证据写入多维表格
- [ ] ModelInvocation 记录 token 用量（预算管控）
- [ ] AgentRun 异常 → FAILED → WorkItem BLOCKED → 主理人需显式重试

## 阶段 D：审批交付
- [ ] 高风险操作触发飞书审批实例
- [ ] 审批人收到飞书审批通知
- [ ] Mission 状态 → APPROVAL_REQUIRED
- [ ] 审批通过 → 回调云函数 → Mission APPROVED → 执行外部操作
- [ ] 审批拒绝 → Mission BLOCKED → 通知主理人
- [ ] 外部操作执行（发邮件/IM通知）
- [ ] ExternalOperation 审计日志记录

## 阶段 E：看板与工作区
- [ ] 看板展示全部 active 专家团卡片
- [ ] 卡片显示团队名/主理人/进行中任务数/待审批数/最近状态时间
- [ ] 卡片点击跳转团队工作区
- [ ] 看板每 30 秒自动刷新
- [ ] 工作区按团队维度聚合 Mission/WorkItem/AgentRun/成员/章程/Skill/协作
- [ ] Mission 列表支持进行中/全部过滤
- [ ] WorkItem 和 AgentRun 详情可展开
- [ ] 显式区分长期成员（AgentProfile）与执行实例（AgentRun）
- [ ] 主理人操作按钮可用（生成清单/启动执行/提交审批）
- [ ] 协作请求区可接受/拒绝
- [ ] 工作区每 15 秒自动刷新
- [ ] 章程版本管理（草稿→审核→发布）
- [ ] 运行日志分页查看
- [ ] 邮件归档分页列表+搜索

## 阶段 F：部署与验证
- [ ] 全部云函数上传到妙搭并验证 require lib 正常
- [ ] 全部 HTML 页面上传到妙搭静态资源
- [ ] 妙搭环境变量配置完整（FEISHU_APP_ID/SECRET、LLM_API_KEY、BASE_TOKEN）
- [ ] 妙搭应用发布，可见范围设为 tenant
- [ ] 端到端：飞书工作台点图标 → OAuth 授权 → 进入看板
- [ ] 端到端：发测试邮件 → 事件触发 → dispatch → 看板出现新任务
- [ ] 端到端：生成清单 → 执行 → AgentRun 完成 → 产出 Artifact
- [ ] 端到端：高风险 → 飞书审批 → 通过 → 外部操作 → 闭环
- [ ] 端到端：协作请求 → 接受 → 回传 Artifact
- [ ] 端到端：关电脑后邮件事件仍正常触发（妙搭云端常驻）
- [ ] 旧 Python 脚本已删除（feishu/ 目录）
- [ ] src/workbuddy/ 保持不动
