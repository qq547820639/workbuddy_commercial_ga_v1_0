'use strict';

/**
 * WorkBuddy 运行日志工具。
 * 写 worker_log 表 + 控制台输出；写表失败只 console.error，不抛异常。
 * 日志条数超过 LOG_RETENTION_COUNT 时自动清理旧行，保留最近 N 条。
 *
 * 仅依赖 Node.js 内置模块（通过 db.js 与 constants.js），不依赖任何第三方库。
 *
 * 注意：db 操作为异步，logger 函数采用 fire-and-forget 模式（不阻塞主流程）。
 * 表名 worker_log 与 schema.sql / get_status.js 保持一致。
 */

const db = require('./db');
const {
  LOG_LEVELS,
  LOG_LEVEL_PRIORITY,
  LOG_RETENTION_COUNT,
  WORKER_LOG_TABLE,
} = require('./constants');

/** 日志 message 字段最大长度（超出截断，避免写爆 TEXT 字段） */
const MAX_MESSAGE_LENGTH = 4000;

/**
 * 截断日志消息，避免超长 message 写爆 TEXT 字段。
 * @param {string} message - 原始消息
 * @returns {string} 截断后的消息（最长 MAX_MESSAGE_LENGTH 字符）
 */
function _truncate(message) {
  const s = String(message == null ? '' : message);
  return s.length <= MAX_MESSAGE_LENGTH ? s : s.slice(0, MAX_MESSAGE_LENGTH) + '…';
}

/**
 * 校验日志级别是否合法。
 * @param {string} level - 日志级别
 * @returns {boolean} true 表示合法
 */
function _isValidLevel(level) {
  return Object.prototype.hasOwnProperty.call(LOG_LEVEL_PRIORITY, level);
}

/**
 * 写一条日志到 worker_log 表 + 控制台。
 * 写表失败只 console.error，不抛异常（避免日志调用拖垮主流程）。
 * @param {string} level - 日志级别（DEBUG/INFO/WARN/ERROR）
 * @param {string} message - 日志消息
 * @returns {void}
 */
function log(level, message) {
  if (!_isValidLevel(level)) {
    // 非法级别回退到 INFO，并附原级别
    console.warn(`[logger] 非法日志级别 "${level}"，回退为 INFO`);
    message = `[${level}] ${message}`;
    level = LOG_LEVELS.INFO;
  }
  const msg = _truncate(message);
  // 控制台按级别选择输出方式，保证即使 DB 写失败也能看到
  if (level === LOG_LEVELS.ERROR) {
    console.error(`[ERROR] ${msg}`);
  } else if (level === LOG_LEVELS.WARN) {
    console.warn(`[WARN] ${msg}`);
  } else if (level === LOG_LEVELS.DEBUG) {
    console.log(`[DEBUG] ${msg}`);
  } else {
    console.log(`[INFO] ${msg}`);
  }
  // fire-and-forget 写表；失败只 console.error，不抛异常
  db
    .insert(WORKER_LOG_TABLE, { log_level: level, message: msg })
    .catch(function (err) {
      console.error(`[logger] 写 ${WORKER_LOG_TABLE} 表失败：${err.message}`);
    });
  // 异步清理旧日志，不阻塞主流程（失败静默）
  db
    .execute(
      `DELETE FROM ${WORKER_LOG_TABLE} WHERE id NOT IN ` +
        `(SELECT id FROM (SELECT id FROM ${WORKER_LOG_TABLE} ORDER BY id DESC LIMIT ?) t)`,
      [LOG_RETENTION_COUNT]
    )
    .catch(function () {
      // 清理失败不影响主流程，静默
    });
}

/**
 * 写一条 DEBUG 级别日志。
 * @param {string} message - 日志消息
 * @returns {void}
 */
function debug(message) {
  log(LOG_LEVELS.DEBUG, message);
}

/**
 * 写一条 INFO 级别日志。
 * @param {string} message - 日志消息
 * @returns {void}
 */
function info(message) {
  log(LOG_LEVELS.INFO, message);
}

/**
 * 写一条 WARN 级别日志。
 * @param {string} message - 日志消息
 * @returns {void}
 */
function warn(message) {
  log(LOG_LEVELS.WARN, message);
}

/**
 * 写一条 ERROR 级别日志。
 * @param {string} message - 日志消息
 * @returns {void}
 */
function error(message) {
  log(LOG_LEVELS.ERROR, message);
}

module.exports = {
  log: log,
  debug: debug,
  info: info,
  warn: warn,
  error: error,
};
