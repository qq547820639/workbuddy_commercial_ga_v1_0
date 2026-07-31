"""飞书多维表格 Base 表结构定义。

定义 WorkBuddy 核心域数据在多维表格中的表和字段 schema。
字段类型仅用基础类型（text/select/datetime/number/checkbox），不用 formula/lookup。
所有字段类型都支持可选 description（见 lark-base-field-json.md）。
"""

# 邮件归档表 — 对应 WorkBuddy MailMessage
MAIL_TABLE = {
    "name": "邮件归档",
    "fields": [
        {"name": "message_id", "type": "text", "description": "飞书邮件 message_id"},
        {"name": "subject", "type": "text", "description": "邮件主题"},
        {"name": "from_name", "type": "text", "description": "发件人姓名"},
        {"name": "from_mail", "type": "text", "description": "发件人邮箱"},
        {"name": "received_at", "type": "datetime", "description": "接收时间"},
        {"name": "body_preview", "type": "text", "description": "正文预览（前300字）"},
        {"name": "labels", "type": "text", "description": "标签（逗号分隔）"},
        {"name": "processing_status", "type": "select", "options": [
            {"name": "NEW"}, {"name": "NOTIFIED"}, {"name": "ARCHIVED"}
        ], "description": "处理状态"},
    ],
}

# 团队表 — 对应 WorkBuddy Team
TEAM_TABLE = {
    "name": "团队",
    "fields": [
        {"name": "team_key", "type": "text", "description": "团队唯一标识"},
        {"name": "name", "type": "text", "description": "团队名称"},
        {"name": "active", "type": "checkbox", "description": "是否启用"},
    ],
}

# 智能体表 — 对应 WorkBuddy Agent
AGENT_TABLE = {
    "name": "智能体",
    "fields": [
        {"name": "team", "type": "text", "description": "所属团队"},
        {"name": "role_key", "type": "text", "description": "角色标识"},
        {"name": "name", "type": "text", "description": "智能体名称"},
        {"name": "is_lead", "type": "checkbox", "description": "是否主理人"},
        {"name": "status", "type": "select", "options": [
            {"name": "active"}, {"name": "inactive"}
        ], "description": "状态"},
    ],
}

# 任务表 — 对应 WorkBuddy Mission
MISSION_TABLE = {
    "name": "任务",
    "fields": [
        {"name": "title", "type": "text", "description": "任务标题"},
        {"name": "objective", "type": "text", "description": "目标说明"},
        {"name": "status", "type": "select", "options": [
            {"name": "INGESTED"}, {"name": "ACCEPTED"}, {"name": "PLANNED"},
            {"name": "APPROVED"}, {"name": "EXECUTING"}, {"name": "REVIEWING"},
            {"name": "CLOSED"}
        ], "description": "任务状态"},
        {"name": "risk_level", "type": "select", "options": [
            {"name": "low"}, {"name": "medium"}, {"name": "high"}
        ], "description": "风险等级"},
        {"name": "source_type", "type": "text", "description": "来源类型"},
        {"name": "team", "type": "text", "description": "所属团队"},
        {"name": "lead_agent", "type": "text", "description": "主理智能体"},
    ],
}

# 工作项表 — 对应 WorkBuddy WorkItem
WORK_ITEM_TABLE = {
    "name": "工作项",
    "fields": [
        {"name": "mission", "type": "text", "description": "所属任务"},
        {"name": "item_key", "type": "text", "description": "工作项标识"},
        {"name": "title", "type": "text", "description": "工作项标题"},
        {"name": "status", "type": "select", "options": [
            {"name": "DRAFT"}, {"name": "READY"}, {"name": "IN_PROGRESS"},
            {"name": "IN_REVIEW"}, {"name": "DONE"}, {"name": "BLOCKED"}
        ], "description": "工作项状态"},
        {"name": "assigned_agent", "type": "text", "description": "负责智能体"},
        {"name": "sequence", "type": "number", "description": "排序序号"},
    ],
}

# 智能体运行记录表 — 对应 WorkBuddy AgentRun
AGENT_RUN_TABLE = {
    "name": "智能体运行",
    "fields": [
        {"name": "mission", "type": "text", "description": "所属任务"},
        {"name": "work_item", "type": "text", "description": "关联工作项"},
        {"name": "agent", "type": "text", "description": "执行智能体"},
        {"name": "status", "type": "select", "options": [
            {"name": "CREATED"}, {"name": "RUNNING"}, {"name": "COMPLETED"}, {"name": "FAILED"}
        ], "description": "运行状态"},
        {"name": "started_at", "type": "datetime", "description": "开始时间"},
        {"name": "finished_at", "type": "datetime", "description": "结束时间"},
    ],
}

ALL_TABLES = [
    MAIL_TABLE,
    TEAM_TABLE,
    AGENT_TABLE,
    MISSION_TABLE,
    WORK_ITEM_TABLE,
    AGENT_RUN_TABLE,
]
