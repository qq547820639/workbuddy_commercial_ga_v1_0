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

# 配置表 — key-value 结构，供小白用户在飞书多维表格中直接编辑配置
CONFIG_TABLE = {
    "name": "配置",
    "fields": [
        {"name": "config_key", "type": "text", "description": "配置键名（如 NOTIFY_CHAT_ID）"},
        {"name": "config_value", "type": "text", "description": "配置值"},
    ],
}

# Worker 运行状态表 — 单行表（id 固定为 1），watch_worker 每轮更新
WORKER_STATUS_TABLE = {
    "name": "运行状态",
    "fields": [
        {"name": "is_running", "type": "checkbox", "description": "是否运行中"},
        {"name": "last_poll_at", "type": "datetime", "description": "最近轮询时间"},
        {"name": "total_notified", "type": "number", "description": "累计通知数"},
        {"name": "error_count", "type": "number", "description": "错误次数"},
    ],
}

# 运行日志表 — watch_worker 每轮写日志，保留最近 N 条
WORKER_LOG_TABLE = {
    "name": "运行日志",
    "fields": [
        {"name": "log_level", "type": "select", "options": [
            {"name": "INFO"}, {"name": "WARN"}, {"name": "ERROR"}
        ], "description": "日志级别"},
        {"name": "message", "type": "text", "description": "日志内容"},
        {"name": "created_at", "type": "datetime", "description": "记录时间"},
    ],
}

ALL_TABLES = [
    MAIL_TABLE,
    CONFIG_TABLE,
    WORKER_STATUS_TABLE,
    WORKER_LOG_TABLE,
    TEAM_TABLE,
    AGENT_TABLE,
    MISSION_TABLE,
    WORK_ITEM_TABLE,
    AGENT_RUN_TABLE,
]

# 预填配置默认值（base_init.py 创建 CONFIG_TABLE 后写入）
DEFAULT_CONFIG_ROWS = [
    {"config_key": "NOTIFY_CHAT_ID", "config_value": "oc_716f4d911915d3e3d91a053e1a80f4a8"},
    {"config_key": "POLL_INTERVAL", "config_value": "60"},
    {"config_key": "MAX_RECONNECT_BACKOFF", "config_value": "300"},
]

# 运行状态表初始单行（id 固定为 1）
DEFAULT_WORKER_STATUS_ROW = {
    "is_running": False,
    "last_poll_at": None,
    "total_notified": 0,
    "error_count": 0,
}
