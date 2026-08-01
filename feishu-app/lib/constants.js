'use strict';

/**
 * WorkBuddy 共享常量。
 * 集中定义跨模块复用的应用常量：飞书 API 基址、退出码、日志级别、
 * 卡片模板、邮件事件类型、Mission/WorkItem/AgentRun 状态枚举、
 * 审批触发类型枚举等。
 *
 * 注意：所有值均为纯常量，不依赖任何第三方库，可直接被云函数与 lib 模块 require。
 */

/**
 * 飞书 OpenAPI 基础地址。
 * OAuth、邮箱、IM、审批等接口均以此为前缀。
 * 可通过环境变量 FEISHU_OPENAPI_BASE 覆盖（用于私有化/测试环境）。
 */
const FEISHU_OPENAPI_BASE =
  process.env.FEISHU_OPENAPI_BASE || 'https://open.feishu.cn/open-apis';

/** 退出码语义（与 feishu/watch_worker.py 保持一致） */
const EXIT_CODES = {
  /** 0 = 正常退出 */
  OK: 0,
  /** 2 = 启动配置失败 */
  CONFIG: 2,
  /** 3 = auth 失败 / token 过期，需人工 relogin */
  AUTH: 3,
};

/**
 * 日志级别。DEBUG 用于详细调试信息，生产环境可按需关闭写表。
 */
const LOG_LEVELS = {
  DEBUG: 'DEBUG',
  INFO: 'INFO',
  WARN: 'WARN',
  ERROR: 'ERROR',
};

/**
 * 日志级别优先级（数值越小优先级越高），用于过滤低于阈级别的日志。
 * 例如只输出 WARN 及以上：levelPriority[LOG_LEVELS.WARN] <= levelPriority[当前级别]。
 */
const LOG_LEVEL_PRIORITY = {
  DEBUG: 10,
  INFO: 20,
  WARN: 30,
  ERROR: 40,
};

/** 邮件处理状态 */
const PROCESSING_STATUS = {
  NEW: 'NEW',
  NOTIFIED: 'NOTIFIED',
  ARCHIVED: 'ARCHIVED',
  FAILED: 'FAILED',
};

/**
 * 邮件事件类型常量。
 * 用于事件订阅场景（预留）与邮件分类，参考飞书邮箱 OpenAPI 事件回调。
 */
const MAIL_EVENT_TYPES = {
  /** 新邮件到达 */
  MAIL_RECEIVED: 'mail.received',
  /** 邮件已读 */
  MAIL_READ: 'mail.read',
  /** 邮件已发送 */
  MAIL_SENT: 'mail.sent',
  /** 邮件被标记/分类 */
  MAIL_LABELED: 'mail.labeled',
  /** 邮件被删除 */
  MAIL_DELETED: 'mail.deleted',
};

/**
 * Mission（任务/使命）状态枚举。
 * 描述一封邮件触发的协作任务从创建到完成的生命周期。
 */
const MISSION_STATUS = {
  /** 已创建，待分配 */
  CREATED: 'CREATED',
  /** 已分配 owner，进行中 */
  IN_PROGRESS: 'IN_PROGRESS',
  /** 等待审批 */
  PENDING_APPROVAL: 'PENDING_APPROVAL',
  /** 已完成 */
  COMPLETED: 'COMPLETED',
  /** 已取消 */
  CANCELLED: 'CANCELLED',
  /** 处理失败 */
  FAILED: 'FAILED',
};

/**
 * WorkItem（工作项）状态枚举。
 * 描述 Mission 拆解出的具体工作项的执行状态。
 */
const WORK_ITEM_STATUS = {
  /** 待处理 */
  PENDING: 'PENDING',
  /** 处理中 */
  IN_PROGRESS: 'IN_PROGRESS',
  /** 已阻塞（等待外部输入） */
  BLOCKED: 'BLOCKED',
  /** 已完成 */
  DONE: 'DONE',
  /** 已跳过 */
  SKIPPED: 'SKIPPED',
  /** 处理失败 */
  FAILED: 'FAILED',
};

/**
 * AgentRun（Agent 执行记录）状态枚举。
 * 描述单次 Agent 运行（如 AI 处理一轮邮件）的状态。
 */
const AGENT_RUN_STATUS = {
  /** 已创建，待执行 */
  CREATED: 'CREATED',
  /** 运行中 */
  RUNNING: 'RUNNING',
  /** 已成功完成 */
  SUCCEEDED: 'SUCCEEDED',
  /** 运行失败 */
  FAILED: 'FAILED',
  /** 已超时 */
  TIMEOUT: 'TIMEOUT',
  /** 已取消 */
  CANCELLED: 'CANCELLED',
};

/**
 * 审批触发类型枚举。
 * 标识触发飞书审批的不同业务场景，用于审批实例创建与归档分类。
 */
const APPROVAL_TRIGGER_TYPES = {
  /** 退款审批 */
  REFUND: 'refund',
  /** 补偿审批 */
  COMPENSATION: 'compensation',
  /** 法务受理审批 */
  LEGAL_ADMISSION: 'legal_admission',
  /** 解决方案承诺审批 */
  RESOLUTION_COMMITMENT: 'resolution_commitment',
  /** 外部发送审批（对外发信/对外动作） */
  EXTERNAL_SEND: 'external_send',
};

/** 默认轮询间隔（秒） */
const DEFAULT_POLL_INTERVAL = 60;

/** 默认指数退避上限（秒） */
const DEFAULT_MAX_BACKOFF = 300;

/** 邮件预览最大长度 */
const BODY_PREVIEW_LIMIT = 300;

/** 邮件主题截断长度 */
const SUBJECT_TRUNCATE_LIMIT = 60;

/** 日志表保留条数（超过自动清理旧行） */
const LOG_RETENTION_COUNT = 1000;

/** 运行日志表名（与 schema.sql 保持一致） */
const WORKER_LOG_TABLE = 'worker_log';

/** 配置表名（与 schema.sql 保持一致） */
const CONFIG_TABLE = 'config';

/**
 * 邮件通知卡片模板（Card 2.0）。
 * 结构参考 feishu/notifier.py build_card：
 *   header 显示"新邮件" + 主题副标题；
 *   body 含发件人 / 时间 / 分隔线 / 正文预览。
 * 用 buildMailCard(feishu-im.js) 填充具体字段后发送。
 */
const CARD_TEMPLATE = {
  schema: '2.0',
  config: {
    update_multi: true,
    width_mode: 'default',
  },
  header: {
    title: { tag: 'plain_text', content: '新邮件' },
    subtitle: { tag: 'plain_text', content: '' },
    template: 'blue',
  },
  body: {
    direction: 'vertical',
    padding: '12px 12px 20px 12px',
    elements: [],
  },
};

module.exports = {
  FEISHU_OPENAPI_BASE,
  EXIT_CODES,
  LOG_LEVELS,
  LOG_LEVEL_PRIORITY,
  PROCESSING_STATUS,
  MAIL_EVENT_TYPES,
  MISSION_STATUS,
  WORK_ITEM_STATUS,
  AGENT_RUN_STATUS,
  APPROVAL_TRIGGER_TYPES,
  DEFAULT_POLL_INTERVAL,
  DEFAULT_MAX_BACKOFF,
  BODY_PREVIEW_LIMIT,
  SUBJECT_TRUNCATE_LIMIT,
  LOG_RETENTION_COUNT,
  WORKER_LOG_TABLE,
  CONFIG_TABLE,
  CARD_TEMPLATE,
};
