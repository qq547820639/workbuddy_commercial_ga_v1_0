'use strict';

/**
 * WorkBuddy 仪表盘状态查询云函数（HTML 控制台前端 GET 调用）。
 *
 * 返回 worker 运行状态 + 归档总数 + 最近 20 条日志，供前端渲染仪表盘。
 *
 * 入口签名说明：妙搭云函数入口约定为 exports.main = async (event, context) => {...}，
 * 具体 event / context 形态需在妙搭环境验证；本函数不依赖入参。
 *
 * 返回结构：
 *   {
 *     ok: true,
 *     data: {
 *       is_running: boolean,
 *       last_poll_at: string|null,
 *       total_notified: number,
 *       error_count: number,
 *       archive_total: number,
 *       recent_logs: Array<{id, log_level, message, created_at}>
 *     }
 *   }
 * 异常返回：{ ok: false, error: string }
 */

const db = require('../lib/db.js');
const logger = require('../lib/logger.js');

/** 最近日志条数 */
const RECENT_LOG_LIMIT = 20;

/**
 * 妙搭云函数入口：查询仪表盘状态数据。
 * @param {Object} [event] - 触发器事件（本函数不使用）
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: boolean, data?: {...}, error?: string }
 */
exports.main = async function (event, context) {
  try {
    // 1. 拿 worker 状态行（id 固定为 1）
    const statusRow = await db.queryOne(
      'SELECT * FROM worker_status WHERE id = 1'
    );

    // 2. 拿归档总数
    const countRow = await db.queryOne(
      'SELECT COUNT(*) AS total FROM mail_archive'
    );
    const archiveTotal =
      countRow && countRow.total != null ? Number(countRow.total) : 0;

    // 3. 拿最近 20 条日志
    const recentLogs = await db.queryAll(
      'SELECT id, log_level, message, created_at FROM worker_log ORDER BY id DESC LIMIT ?',
      [RECENT_LOG_LIMIT]
    );

    const data = {
      is_running: statusRow
        ? !!statusRow.is_running
        : false,
      last_poll_at: statusRow && statusRow.last_poll_at != null
        ? statusRow.last_poll_at
        : null,
      total_notified: statusRow && statusRow.total_notified != null
        ? Number(statusRow.total_notified)
        : 0,
      error_count: statusRow && statusRow.error_count != null
        ? Number(statusRow.error_count)
        : 0,
      archive_total: archiveTotal,
      recent_logs: Array.isArray(recentLogs) ? recentLogs : [],
    };

    return { ok: true, data: data };
  } catch (err) {
    logger.error(
      `get_status: 查询状态异常 err=${err && err.message ? err.message : err}`
    );
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
