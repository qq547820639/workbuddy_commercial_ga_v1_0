'use strict';

/**
 * WorkBuddy 运行日志分页查询云函数（HTML 控制台前端 GET 调用）。
 *
 * 支持按日志级别过滤 + 分页，按 created_at 降序（同秒内按 id 降序作次序）。
 *
 * 入口签名说明：妙搭云函数入口约定为 exports.main = async (event, context) => {...}，
 * GET 参数从 event.queryString 读，兼容直接挂在 event 上的情况。
 *
 * 入参（从 event.queryString 或 event 读）：
 *   - page  页码，默认 1
 *   - size  每页条数，默认 20，钳制到 [1, 100]
 *   - level 可选，按 log_level 精确过滤（INFO/WARN/ERROR/DEBUG）
 *
 * 返回结构：
 *   {
 *     ok: true,
 *     data: {
 *       logs: Array<{ id, log_level, message, created_at }>,
 *       total: number, page: number, size: number
 *     }
 *   }
 * 异常返回：{ ok: false, error: string }
 */

const db = require('../lib/db.js');
const logger = require('../lib/logger.js');
const { WORKER_LOG_TABLE } = require('../lib/constants.js');

/** 每页默认条数 */
const DEFAULT_PAGE_SIZE = 20;
/** 每页最大条数 */
const MAX_PAGE_SIZE = 100;
/** 合法日志级别白名单（非法值忽略过滤） */
var VALID_LEVELS = { INFO: 1, WARN: 1, ERROR: 1, DEBUG: 1 };

/**
 * 从 event 中解析入参，兼容 event.queryString 和 event 顶层两种形态。
 * @param {Object} event - 妙搭事件对象
 * @returns {{page: number, size: number, level: string}}
 */
function _parseParams(event) {
  var src = (event && event.queryString) || event || {};
  var page = parseInt(src.page, 10);
  if (isNaN(page) || page < 1) {
    page = 1;
  }
  var size = parseInt(src.size, 10);
  if (isNaN(size) || size < 1) {
    size = DEFAULT_PAGE_SIZE;
  }
  if (size > MAX_PAGE_SIZE) {
    size = MAX_PAGE_SIZE;
  }
  var level =
    src.level != null ? String(src.level).trim().toUpperCase() : '';
  // 非白名单级别视为不过滤
  if (level && !Object.prototype.hasOwnProperty.call(VALID_LEVELS, level)) {
    level = '';
  }
  return { page: page, size: size, level: level };
}

/**
 * 妙搭云函数入口：分页查询运行日志。
 * @param {Object} [event] - 触发器事件
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: boolean, data?: {...}, error?: string }
 */
exports.main = async function (event, context) {
  try {
    // 1. 解析 page/size/level
    var params = _parseParams(event);
    var page = params.page;
    var size = params.size;
    var level = params.level;
    var offset = (page - 1) * size;

    // 2. 构造 WHERE：level 非空时精确匹配
    var whereSql = ' WHERE 1=1';
    var sqlParams = [];
    if (level) {
      whereSql += ' AND log_level = ?';
      sqlParams.push(level);
    }

    // 3. 查总数
    var countRow = await db.queryOne(
      'SELECT COUNT(*) AS total FROM ' + WORKER_LOG_TABLE + whereSql,
      sqlParams
    );
    var total =
      countRow && countRow.total != null ? Number(countRow.total) : 0;

    // 4. 查分页数据（created_at 降序，同秒按 id 降序）
    var logs = await db.queryAll(
      'SELECT id, log_level, message, created_at FROM ' +
        WORKER_LOG_TABLE +
        whereSql +
        ' ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?',
      sqlParams.concat([size, offset])
    );

    return {
      ok: true,
      data: {
        logs: Array.isArray(logs) ? logs : [],
        total: total,
        page: page,
        size: size,
      },
    };
  } catch (err) {
    logger.error(
      'get_logs: 查询日志异常 err=' +
        (err && err.message ? err.message : err)
    );
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
