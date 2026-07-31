'use strict';

/**
 * WorkBuddy 共享常量。
 * 包含退出码、日志级别、卡片模板等跨模块复用的常量。
 */

/** 退出码语义（与 feishu/watch_worker.py 保持一致） */
const EXIT_CODES = {
  /** 0 = 正常退出 */
  OK: 0,
  /** 2 = 启动配置失败 */
  CONFIG: 2,
  /** 3 = auth 失败 / token 过期，需人工 relogin */
  AUTH: 3,
};

/** 日志级别 */
const LOG_LEVELS = {
  INFO: 'INFO',
  WARN: 'WARN',
  ERROR: 'ERROR',
};

/** 邮件处理状态 */
const PROCESSING_STATUS = {
  NEW: 'NEW',
  NOTIFIED: 'NOTIFIED',
  ARCHIVED: 'ARCHIVED',
  FAILED: 'FAILED',
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
  EXIT_CODES,
  LOG_LEVELS,
  PROCESSING_STATUS,
  DEFAULT_POLL_INTERVAL,
  DEFAULT_MAX_BACKOFF,
  BODY_PREVIEW_LIMIT,
  SUBJECT_TRUNCATE_LIMIT,
  LOG_RETENTION_COUNT,
  CARD_TEMPLATE,
};
