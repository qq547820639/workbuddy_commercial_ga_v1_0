'use strict';

/**
 * WorkBuddy 飞书多维表格（Base）表结构定义。
 *
 * 定义 WorkBuddy 核心域数据在多维表格中的 12 张表和字段 schema。
 * 字段类型仅用飞书多维表格支持的基础类型：
 *   text / number / select / datetime / checkbox / url
 * 不使用 formula / lookup，降低复杂度。
 *
 * 每张表结构：
 *   - tableKey:  英文表标识（如 mail_archive）
 *   - name:      中文表名（如 邮件归档）
 *   - ormModel:  对应的 WorkBuddy ORM 模型类名（见 src/workbuddy/db/models.py）
 *   - fields:    字段数组，每个字段含：
 *       name        字段名（多维表格列名）
 *       type        字段类型（text/number/select/datetime/checkbox/url）
 *       orm         映射到 ORM 模型的属性路径（如 Mission.title）
 *       options     select 类型的可选值数组（每项 { name }）
 *       description 字段说明
 *
 * 状态枚举对照 src/workbuddy/domain/state_machine.py 中的 StrEnum 定义。
 */

// ---------------------------------------------------------------------------
// 状态枚举可选值（对照 state_machine.py，保证与后端一致）
// ---------------------------------------------------------------------------

/** 邮件处理状态（对照 constants.PROCESSING_STATUS） */
var MAIL_PROCESSING_OPTIONS = [
  { name: 'NEW' },
  { name: 'NOTIFIED' },
  { name: 'ARCHIVED' },
  { name: 'FAILED' },
];

/** 智能体状态（对照 AgentProfile.status） */
var AGENT_STATUS_OPTIONS = [
  { name: 'active' },
  { name: 'inactive' },
];

/** 任务状态（对照 MissionStatus） */
var MISSION_STATUS_OPTIONS = [
  { name: 'INGESTED' },
  { name: 'DISPATCH_REVIEW' },
  { name: 'ROUTED' },
  { name: 'LEAD_TRIAGE' },
  { name: 'PLANNING' },
  { name: 'READY' },
  { name: 'EXECUTING' },
  { name: 'LEAD_REVIEW' },
  { name: 'APPROVAL_REQUIRED' },
  { name: 'APPROVED' },
  { name: 'ACTION_EXECUTING' },
  { name: 'VERIFYING' },
  { name: 'COMPLETED' },
  { name: 'NEEDS_INFORMATION' },
  { name: 'BLOCKED' },
  { name: 'FAILED' },
  { name: 'CANCELLED' },
  { name: 'UNKNOWN' },
];

/** 风险等级（对照 DispatchDecision / Mission.risk_level） */
var RISK_LEVEL_OPTIONS = [
  { name: 'low' },
  { name: 'medium' },
  { name: 'high' },
  { name: 'unknown' },
];

/** 工作项状态（对照 WorkItemStatus） */
var WORK_ITEM_STATUS_OPTIONS = [
  { name: 'DRAFT' },
  { name: 'READY' },
  { name: 'WAITING_DEPENDENCY' },
  { name: 'ASSIGNED' },
  { name: 'RUNNING' },
  { name: 'SUBMITTED' },
  { name: 'ACCEPTED' },
  { name: 'REVISION_REQUIRED' },
  { name: 'BLOCKED' },
  { name: 'FAILED' },
  { name: 'CANCELLED' },
];

/** 执行记录状态（对照 AgentRunStatus） */
var AGENT_RUN_STATUS_OPTIONS = [
  { name: 'CREATED' },
  { name: 'CONTEXT_PREPARED' },
  { name: 'RUNNING' },
  { name: 'TOOL_WAIT' },
  { name: 'OUTPUT_SUBMITTED' },
  { name: 'CLOSED' },
  { name: 'TIMED_OUT' },
  { name: 'FAILED' },
  { name: 'CANCELLED' },
  { name: 'QUARANTINED' },
];

/** 审批状态（对照 ApprovalStatus） */
var APPROVAL_STATUS_OPTIONS = [
  { name: 'DRAFT' },
  { name: 'PENDING' },
  { name: 'APPROVED' },
  { name: 'REJECTED' },
  { name: 'CHANGES_REQUESTED' },
  { name: 'EXPIRED' },
  { name: 'INVALIDATED' },
  { name: 'CANCELLED' },
];

/** 证据验证状态（对照 Evidence.verification_status） */
var EVIDENCE_STATUS_OPTIONS = [
  { name: 'unverified' },
  { name: 'verified' },
  { name: 'rejected' },
];

/** 协作请求状态（对照 CollaborationRequestStatus） */
var COLLABORATION_STATUS_OPTIONS = [
  { name: 'PENDING' },
  { name: 'ACCEPTED' },
  { name: 'IN_PROGRESS' },
  { name: 'COMPLETED' },
  { name: 'DECLINED' },
  { name: 'FAILED' },
  { name: 'CANCELLED' },
];

/** 日志级别 */
var LOG_LEVEL_OPTIONS = [
  { name: 'INFO' },
  { name: 'WARN' },
  { name: 'ERROR' },
];

// ---------------------------------------------------------------------------
// 12 张表定义
// ---------------------------------------------------------------------------

/**
 * 1. 邮件归档表 — 对应 MailMessage
 *    飞书邮件轮询后归档的邮件元数据，用于跨重启去重与状态追踪。
 */
var MAIL_ARCHIVE_TABLE = {
  tableKey: 'mail_archive',
  name: '邮件归档',
  ormModel: 'MailMessage',
  fields: [
    { name: 'message_id', type: 'text', orm: 'MailMessage.provider_message_id', description: '飞书邮件 message_id' },
    { name: 'subject', type: 'text', orm: 'MailMessage.subject', description: '邮件主题' },
    { name: 'from_name', type: 'text', orm: 'MailMessage.sender (解析姓名)', description: '发件人姓名' },
    { name: 'from_mail', type: 'text', orm: 'MailMessage.sender (解析邮箱)', description: '发件人邮箱' },
    { name: 'received_at', type: 'datetime', orm: 'MailMessage.received_at', description: '接收时间' },
    { name: 'body_preview', type: 'text', orm: 'MailMessage.body_text (前300字)', description: '正文预览（前300字）' },
    { name: 'labels', type: 'text', orm: 'MailMessage.labels', description: '标签（逗号分隔）' },
    { name: 'processing_status', type: 'select', options: MAIL_PROCESSING_OPTIONS, orm: 'MailMessage.processing_status', description: '处理状态' },
  ],
};

/**
 * 2. 团队表 — 对应 TeamDefinition + TeamConstitutionVersion
 *    专家团定义，mission 来源于团队章程配置。
 */
var TEAMS_TABLE = {
  tableKey: 'teams',
  name: '团队',
  ormModel: 'TeamDefinition',
  fields: [
    { name: 'team_key', type: 'text', orm: 'TeamDefinition.team_key', description: '团队唯一标识' },
    { name: 'name', type: 'text', orm: 'TeamDefinition.name', description: '团队名称' },
    { name: 'mission', type: 'text', orm: 'TeamConstitutionVersion.config.mission', description: '团队使命' },
    { name: 'active', type: 'checkbox', orm: 'TeamDefinition.active', description: '是否启用' },
    { name: 'lead_role_key', type: 'text', orm: 'TeamConstitutionVersion.config.lead_role.key', description: '主理人角色标识' },
    { name: 'lead_role_name', type: 'text', orm: 'TeamConstitutionVersion.config.lead_role.name', description: '主理人角色名称' },
  ],
};

/**
 * 3. 智能体表 — 对应 AgentProfile
 *    每个团队下的主理人与子角色智能体定义。
 */
var AGENTS_TABLE = {
  tableKey: 'agents',
  name: '智能体',
  ormModel: 'AgentProfile',
  fields: [
    { name: 'team_key', type: 'text', orm: 'TeamDefinition.team_key (经 team_id 关联)', description: '所属团队标识' },
    { name: 'role_key', type: 'text', orm: 'AgentProfile.role_key', description: '角色标识' },
    { name: 'name', type: 'text', orm: 'AgentProfile.name', description: '智能体名称' },
    { name: 'is_lead', type: 'checkbox', orm: 'AgentProfile.is_lead', description: '是否主理人' },
    { name: 'status', type: 'select', options: AGENT_STATUS_OPTIONS, orm: 'AgentProfile.status', description: '智能体状态' },
    { name: 'responsibilities', type: 'text', orm: 'AgentProfile.profile.responsibilities', description: '职责列表（逗号分隔）' },
  ],
};

/**
 * 4. 任务表 — 对应 Mission
 *    邮件驱动的协作任务，状态机见 MissionStatus。
 */
var MISSIONS_TABLE = {
  tableKey: 'missions',
  name: '任务',
  ormModel: 'Mission',
  fields: [
    { name: 'title', type: 'text', orm: 'Mission.title', description: '任务标题' },
    { name: 'objective', type: 'text', orm: 'Mission.objective', description: '目标说明' },
    { name: 'status', type: 'select', options: MISSION_STATUS_OPTIONS, orm: 'Mission.status', description: '任务状态' },
    { name: 'risk_level', type: 'select', options: RISK_LEVEL_OPTIONS, orm: 'Mission.risk_level', description: '风险等级' },
    { name: 'source_type', type: 'text', orm: 'Mission.source_type', description: '来源类型' },
    { name: 'source_id', type: 'text', orm: 'Mission.source_id', description: '来源标识' },
    { name: 'team_key', type: 'text', orm: 'TeamDefinition.team_key (经 primary_team_id 关联)', description: '所属团队标识' },
    { name: 'lead_agent_name', type: 'text', orm: 'AgentProfile.name (经 lead_agent_profile_id 关联)', description: '主理智能体名称' },
    { name: 'created_at', type: 'datetime', orm: 'Mission.created_at', description: '创建时间' },
  ],
};

/**
 * 5. 工作项表 — 对应 WorkItem
 *    任务拆解出的执行步骤，含依赖关系与分配的技能。
 */
var WORK_ITEMS_TABLE = {
  tableKey: 'work_items',
  name: '工作项',
  ormModel: 'WorkItem',
  fields: [
    { name: 'mission_id', type: 'text', orm: 'WorkItem.mission_id', description: '所属任务 ID' },
    { name: 'item_key', type: 'text', orm: 'WorkItem.item_key', description: '工作项标识' },
    { name: 'title', type: 'text', orm: 'WorkItem.title', description: '工作项标题' },
    { name: 'status', type: 'select', options: WORK_ITEM_STATUS_OPTIONS, orm: 'WorkItem.status', description: '工作项状态' },
    { name: 'assigned_agent_name', type: 'text', orm: 'AgentProfile.name (经 assigned_agent_profile_id 关联)', description: '负责智能体名称' },
    { name: 'assigned_role', type: 'text', orm: 'AgentProfile.role_key', description: '分配角色标识' },
    { name: 'skill_name', type: 'text', orm: 'SkillRelease (经 skill_release_id 关联)', description: '关联技能名称' },
    { name: 'sequence', type: 'number', orm: 'WorkItem.sequence', description: '排序序号' },
    { name: 'depends_on', type: 'text', orm: 'WorkItemDependency.depends_on_id (逗号分隔 item_key)', description: '依赖工作项（逗号分隔）' },
  ],
};

/**
 * 6. 执行记录表 — 对应 AgentRun
 *    智能体单次执行实例的状态与时间线。
 */
var AGENT_RUNS_TABLE = {
  tableKey: 'agent_runs',
  name: '执行记录',
  ormModel: 'AgentRun',
  fields: [
    { name: 'mission_id', type: 'text', orm: 'AgentRun.mission_id', description: '所属任务 ID' },
    { name: 'work_item_id', type: 'text', orm: 'AgentRun.work_item_id', description: '关联工作项 ID' },
    { name: 'agent_name', type: 'text', orm: 'AgentProfile.name (经 agent_profile_id 关联)', description: '执行智能体名称' },
    { name: 'status', type: 'select', options: AGENT_RUN_STATUS_OPTIONS, orm: 'AgentRun.status', description: '运行状态' },
    { name: 'started_at', type: 'datetime', orm: 'AgentRun.started_at', description: '开始时间' },
    { name: 'finished_at', type: 'datetime', orm: 'AgentRun.finished_at', description: '结束时间' },
    { name: 'close_reason', type: 'text', orm: 'AgentRun.close_reason', description: '关闭原因' },
    { name: 'context_cleared', type: 'checkbox', orm: 'AgentRun.context_cleared', description: '上下文是否已清理' },
  ],
};

/**
 * 7. 审批请求表 — 对应 ApprovalRequest + ApprovalDecision
 *    需人工决策的审批项，含触发类型与决策记录。
 */
var APPROVALS_TABLE = {
  tableKey: 'approvals',
  name: '审批请求',
  ormModel: 'ApprovalRequest',
  fields: [
    { name: 'mission_id', type: 'text', orm: 'ApprovalRequest.mission_id', description: '所属任务 ID' },
    { name: 'trigger_type', type: 'text', orm: 'ApprovalRequest.exact_action (派生)', description: '审批触发类型' },
    { name: 'status', type: 'select', options: APPROVAL_STATUS_OPTIONS, orm: 'ApprovalRequest.status', description: '审批状态' },
    { name: 'approver', type: 'text', orm: 'ApprovalDecision.actor_id', description: '审批人标识' },
    { name: 'created_at', type: 'datetime', orm: 'ApprovalRequest.created_at', description: '创建时间' },
    { name: 'decided_at', type: 'datetime', orm: 'ApprovalDecision.created_at', description: '决策时间' },
    { name: 'decision_reason', type: 'text', orm: 'ApprovalDecision.reason', description: '决策理由' },
  ],
};

/**
 * 8. 产物表 — 对应 Artifact
 *    智能体执行产出的结构化结果。
 */
var ARTIFACTS_TABLE = {
  tableKey: 'artifacts',
  name: '产物',
  ormModel: 'Artifact',
  fields: [
    { name: 'mission_id', type: 'text', orm: 'Artifact.mission_id', description: '所属任务 ID' },
    { name: 'work_item_id', type: 'text', orm: 'Artifact.work_item_id', description: '关联工作项 ID' },
    { name: 'agent_run_id', type: 'text', orm: 'Artifact.agent_run_id', description: '关联执行记录 ID' },
    { name: 'artifact_type', type: 'text', orm: 'Artifact.artifact_type', description: '产物类型' },
    { name: 'content_hash', type: 'text', orm: 'Artifact.content_hash', description: '内容哈希' },
    { name: 'created_at', type: 'datetime', orm: 'Artifact.created_at', description: '创建时间' },
  ],
};

/**
 * 9. 证据表 — 对应 Evidence
 *    支撑产物与决策的事实证据，含验证状态。
 */
var EVIDENCE_TABLE = {
  tableKey: 'evidence',
  name: '证据',
  ormModel: 'Evidence',
  fields: [
    { name: 'mission_id', type: 'text', orm: 'Evidence.mission_id', description: '所属任务 ID' },
    { name: 'artifact_id', type: 'text', orm: 'Evidence.artifact_id', description: '关联产物 ID' },
    { name: 'evidence_type', type: 'text', orm: 'Evidence.source_type', description: '证据类型' },
    { name: 'status', type: 'select', options: EVIDENCE_STATUS_OPTIONS, orm: 'Evidence.verification_status', description: '验证状态' },
    { name: 'observed_at', type: 'datetime', orm: 'Evidence.created_at', description: '观测时间' },
    { name: 'verified_by', type: 'text', orm: 'GateEvidence.verified_by (运营)', description: '验证人标识' },
  ],
};

/**
 * 10. 协作请求表 — 对应 CollaborationRequest
 *     跨团队协作请求，状态机见 CollaborationRequestStatus。
 */
var COLLABORATIONS_TABLE = {
  tableKey: 'collaborations',
  name: '协作请求',
  ormModel: 'CollaborationRequest',
  fields: [
    { name: 'from_team_key', type: 'text', orm: 'TeamDefinition.team_key (经 sending_team_id 关联)', description: '发起团队标识' },
    { name: 'to_team_key', type: 'text', orm: 'TeamDefinition.team_key (经 receiving_team_id 关联)', description: '接收团队标识' },
    { name: 'objective', type: 'text', orm: 'CollaborationRequest.objective', description: '协作目标' },
    { name: 'expected_artifact', type: 'text', orm: 'CollaborationRequest.expected_artifact', description: '期望产物' },
    { name: 'status', type: 'select', options: COLLABORATION_STATUS_OPTIONS, orm: 'CollaborationRequest.status', description: '协作状态' },
    { name: 'created_at', type: 'datetime', orm: 'CollaborationRequest.created_at', description: '创建时间' },
    { name: 'decided_at', type: 'datetime', orm: 'CollaborationRequest.updated_at (响应时)', description: '决策时间' },
  ],
};

/**
 * 11. 运行日志表 — watch_worker / control_worker 每轮写日志，保留最近 N 条。
 *     运营表，无对应 ORM 模型。
 */
var WORKER_LOGS_TABLE = {
  tableKey: 'worker_logs',
  name: '运行日志',
  ormModel: null,
  fields: [
    { name: 'log_level', type: 'select', options: LOG_LEVEL_OPTIONS, orm: null, description: '日志级别' },
    { name: 'message', type: 'text', orm: null, description: '日志内容' },
    { name: 'created_at', type: 'datetime', orm: null, description: '记录时间' },
  ],
};

/**
 * 12. 配置表 — key-value 结构，供在多维表格中直接编辑运行参数。
 *     运营表，无对应 ORM 模型。
 */
var CONFIG_TABLE = {
  tableKey: 'config',
  name: '配置',
  ormModel: null,
  fields: [
    { name: 'config_key', type: 'text', orm: null, description: '配置键名（如 NOTIFY_CHAT_ID）' },
    { name: 'config_value', type: 'text', orm: null, description: '配置值' },
    { name: 'updated_at', type: 'datetime', orm: null, description: '更新时间' },
  ],
};

// ---------------------------------------------------------------------------
// 全部表定义（顺序即初始化创建顺序）
// ---------------------------------------------------------------------------

var ALL_TABLES = [
  MAIL_ARCHIVE_TABLE,
  TEAMS_TABLE,
  AGENTS_TABLE,
  MISSIONS_TABLE,
  WORK_ITEMS_TABLE,
  AGENT_RUNS_TABLE,
  APPROVALS_TABLE,
  ARTIFACTS_TABLE,
  EVIDENCE_TABLE,
  COLLABORATIONS_TABLE,
  WORKER_LOGS_TABLE,
  CONFIG_TABLE,
];

/**
 * 飞书多维表格字段逻辑类型 → OpenAPI 字段类型 code 映射。
 * 用于 init_base.js 调用 Bitable OpenAPI 创建字段时转换。
 * 参考：https://open.feishu.cn/document/server-docs/docs/bitable-v1/field
 */
var FIELD_TYPE_CODE_MAP = {
  text: 1,        // 多行文本
  number: 2,      // 数字
  select: 3,      // 单选
  datetime: 5,    // 日期时间
  checkbox: 7,    // 复选框
  url: 15,        // 链接
};

module.exports = {
  // 状态枚举可选值
  MAIL_PROCESSING_OPTIONS: MAIL_PROCESSING_OPTIONS,
  AGENT_STATUS_OPTIONS: AGENT_STATUS_OPTIONS,
  MISSION_STATUS_OPTIONS: MISSION_STATUS_OPTIONS,
  RISK_LEVEL_OPTIONS: RISK_LEVEL_OPTIONS,
  WORK_ITEM_STATUS_OPTIONS: WORK_ITEM_STATUS_OPTIONS,
  AGENT_RUN_STATUS_OPTIONS: AGENT_RUN_STATUS_OPTIONS,
  APPROVAL_STATUS_OPTIONS: APPROVAL_STATUS_OPTIONS,
  EVIDENCE_STATUS_OPTIONS: EVIDENCE_STATUS_OPTIONS,
  COLLABORATION_STATUS_OPTIONS: COLLABORATION_STATUS_OPTIONS,
  LOG_LEVEL_OPTIONS: LOG_LEVEL_OPTIONS,
  // 表定义
  MAIL_ARCHIVE_TABLE: MAIL_ARCHIVE_TABLE,
  TEAMS_TABLE: TEAMS_TABLE,
  AGENTS_TABLE: AGENTS_TABLE,
  MISSIONS_TABLE: MISSIONS_TABLE,
  WORK_ITEMS_TABLE: WORK_ITEMS_TABLE,
  AGENT_RUNS_TABLE: AGENT_RUNS_TABLE,
  APPROVALS_TABLE: APPROVALS_TABLE,
  ARTIFACTS_TABLE: ARTIFACTS_TABLE,
  EVIDENCE_TABLE: EVIDENCE_TABLE,
  COLLABORATIONS_TABLE: COLLABORATIONS_TABLE,
  WORKER_LOGS_TABLE: WORKER_LOGS_TABLE,
  CONFIG_TABLE: CONFIG_TABLE,
  ALL_TABLES: ALL_TABLES,
  // 字段类型映射
  FIELD_TYPE_CODE_MAP: FIELD_TYPE_CODE_MAP,
};
