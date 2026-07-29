# Checklist

## 数据模型与状态机
- [x] `TeamConstitutionVersion.config` 支持 `allowed_tools` 字段，缺省时向后兼容
- [x] `CollaborationRequestStatus` 状态机实现：PENDING → ACCEPTED → IN_PROGRESS → COMPLETED / PENDING → DECLINED / ACCEPTED → FAILED
- [x] Alembic 迁移 0020 在空库可执行且不破坏现有数据

## 跨专家团协作
- [x] dispatch 返回 `supporting_team_keys` 非空时，`confirm_dispatch` 自动为每个 supporting team 创建 PENDING 协作请求
- [x] 接收团队主理人可接受/拒绝协作请求，状态机校验通过
- [x] 接受后接收团队执行子任务，提交 Artifact 后发起团队可消费
- [x] 协作请求 COMPLETED 时发起团队工作区显示"Artifact 已回传"
- [x] 拒绝协作时填写理由，发起团队工作区显示理由

## 团队级工具权限
- [x] `create_run_grants` 读取团队 `allowed_tools` 与 Skill.tools 取交集
- [x] 缺省 `allowed_tools` 时按完整 Skill.tools 授权
- [x] 白名单收紧场景测试通过（mail.send 被拒绝）
- [x] 缺省兼容场景测试通过

## 扩充专家团类型
- [x] `config/teams/hr_people.yaml` 包含完整 charter / lead_role / in_scope / out_of_scope / routing_rules / default_workflows / quality_gates / memory_policy / metrics
- [x] `config/teams/finance_ops.yaml` 包含完整 charter / lead_role / in_scope / out_of_scope / routing_rules / default_workflows / quality_gates / memory_policy / metrics
- [x] 新团队引用的 Skill 在 `config/skills/` 存在
- [x] `seed_all` 加载新团队、workflow、AgentProfile、SkillRelease 无错误
- [x] 新团队可被 dispatch 评分阶段纳入候选

## 章程与工作流运行时配置
- [x] 创建章程草稿生成新 `TeamConstitutionVersion`（draft），旧 published 不变
- [x] 状态流转 `draft → reviewing → approved → published` 校验通过
- [x] 新 published 版本成为当前生效章程
- [x] 在途 Mission 仍绑定旧版本（不变更）
- [x] 新建 Mission 使用新版本

## 工作区与看板 API
- [x] `GET /v1/teams/{team_key}/dashboard` 返回卡片聚合数据（主理人、mission 数、WorkItem 数、待审批数、时间戳）
- [x] `GET /v1/teams/{team_key}/workspace` 返回工作区完整聚合
- [x] `GET /v1/teams/{team_key}/missions` 按团队过滤 mission，支持进行中/全部
- [x] 协作请求接受/拒绝/完成端点工作正常
- [x] 章程草稿/审核/发布端点工作正常
- [x] OpenAPI 包含所有新增端点

## 前端看板与工作区
- [x] 看板 AI 员工卡片展示主理人、进行中 mission 数、活跃 WorkItem 数、待审批数、最后更新时间
- [x] 点击卡片跳转 `/team/{team_key}` 工作区页面
- [x] 工作区页面包含：身份与章程、成员、mission 列表、Skill、协作请求、记忆区
- [x] mission 详情显式区分长期 AgentProfile 与一次性 AgentRun，显示 context_cleared 与 close_reason
- [x] 看板每 30 秒自动刷新，工作区每 15 秒自动刷新
- [x] 工作区章程区支持编辑草稿、提交审核、审核通过、发布
- [x] 工作区协作请求区支持接受/拒绝/完成回传
- [x] 前端 JavaScript `node --check` 通过

## 测试与验证
- [x] `test_expert_team_workspace.py` 覆盖看板卡片 API、工作区聚合 API、按团队 mission 过滤、子 agent 生命周期
- [x] `test_collaboration_flow.py` 覆盖协作请求完整闭环（创建→接受→执行→回传→COMPLETED）+ 拒绝路径
- [x] 团队工具权限测试覆盖白名单收紧 + 缺省兼容
- [x] 章程版本隔离测试覆盖在途 mission 不受新版本影响
- [x] `test_alpha_flow.py` 扩展多团队场景（含 supporting team 自动协作）
- [x] `./scripts/verify.sh` 全量验证通过
