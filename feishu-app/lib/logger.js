'use strict';

/**
 * WorkBuddy 运行日志工具。
 * 写 worker_log 表 + console.log；写表失败只 console.error，不抛异常。
 * 日志条数超过 LOG_RETENTION_COUNT 时自动清理旧行，保留最近 N 条。
 *
 * 注意：db 操作为异步，logger 函数采用 fire-and-forget 模式（不阻塞主流程）。
 */

const db = require('./db');
const { LOG_LEVELS, LOG_RETENTION_COUNT } = require('./constants');

/**
 * 截断日志消息，避免超长 message 写爆 TEXT 字段。
 * @param {string} message - 原始消息
 * @returns {string} 截断后的消息（最长 4000 字符）
 */
function _truncate(message) {
  const MAX_LEN = 4000;
  const s = String(message == null ? '' : message);
  return s.length <= MAX_LEN ? s : s.slice(0, MAX_LEN) + '…';
}

/**
 * 写一条日志到 worker_log 表 + console。
 * 写表失败只 console.error，不抛异常（避免日志调用拖垮主流程）。
 * @param {string} level - 日志级别（INFO/WARN/ERROR）
 * @param {string} message - 日志消息
 * @returns {void}
 */
function _log(level, message) {
  const msg = _truncate(message);
  const prefix =
    level === LOG_LEVELS.ERROR ? '[ERROR]' :
    level === LOG_LEVELS.WARN ? '[WARN]' : '[INFO]';
  // console 先输出，保证即使 DB 写失败也能看到
  console.log(`${prefix} ${msg}`);
  // fire-and-forget 写表；失败只 console.error，不抛异常
  db.insert('worker_log', { log_level: level, message: msg })
    .catch(function (err) {
      console.error(`[logger] 写 worker_log 表失败：${err.message}`);
    });
  // 异步清理旧日志，不阻塞主流程（失败静默）
  db.execute(
    'DELETE FROM worker_log WHERE id NOT IN (SELECT id FROM (SELECT id FROM worker_log ORDER BY id DESC LIMIT ?) t)',
    [LOG_RETENTION_COUNT]
  ).catch(function () {
    // 清理失败不影响主流程，静默
  });
}

/**
 * 写一条 INFO 级别日志。
 * @param {string} message - 日志消息
 * @returns {void}
 */
function info(message) {
  _log(LOG_LEVELS.INFO, message);
}

/**
 * 写一条 WARN 级别日志。
 * @param {string} message - 日志消息
 * @returns {void}
 */
function warn(message) {
  _log(LOG_LEVELS.WARN, message);
}

/**
 * 写一条 ERROR 级别日志。
 * @param {string} message - 日志消息
 * @returns {void}
 */
function error(message) {
  _log(LOG_LEVELS.ERROR, message);
}

module.exports = {
  info,
  warn,
  error,
};
