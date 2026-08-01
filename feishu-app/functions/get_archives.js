'use strict';

/**
 * WorkBuddy 归档邮件分页查询云函数（HTML 控制台前端 GET 调用）。
 *
 * 支持按 keyword 模糊搜索 subject / from_name / from_mail + 分页，
 * 按 received_at 降序。
 *
 * 入口签名说明：妙搭云函数入口约定为 exports.main = async (event, context) => {...}，
 * GET 参数从 event.queryString 读，兼容直接挂在 event 上的情况。
 *
 * 入参（从 event.queryString 或 event 读）：
 *   - page    页码，默认 1
 *   - size    每页条数，默认 20，钳制到 [1, 100]
 *   - keyword 可选，按 subject / from_name / from_mail 模糊搜索（OR）
 *
 * 返回结构：
 *   {
 *     ok: true,
 *     data: {
 *       archives: Array<{
 *         message_id, subject, from_name, from_mail,
 *         received_at, body_preview, labels, processing_status
 *       }>,
 *       total: number, page: number, size: number
 *     }
 *   }
 * 异常返回：{ ok: false, error: string }
 */

const db = require('../lib/db.js');
const logger = require('../lib/logger.js');

/** 每页默认条数 */
const DEFAULT_PAGE_SIZE = 20;
/** 每页最大条数 */
const MAX_PAGE_SIZE = 100;

/**
 * 从 event 中解析入参，兼容 event.queryString 和 event 顶层两种形态。
 * @param {Object} event - 妙搭事件对象
 * @returns {{page: number, size: number, keyword: string}}
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
  var keyword =
    src.keyword != null ? String(src.keyword).trim() : '';
  return { page: page, size: size, keyword: keyword };
}

/**
 * 妙搭云函数入口：分页查询归档邮件列表。
 * @param {Object} [event] - 触发器事件
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: boolean, data?: {...}, error?: string }
 */
exports.main = async function (event, context) {
  try {
    // 1. 解析 page/size/keyword
    var params = _parseParams(event);
    var page = params.page;
    var size = params.size;
    var keyword = params.keyword;
    var offset = (page - 1) * size;

    // 2. 构造 WHERE：keyword 非空时对 subject / from_name / from_mail 做 OR LIKE
    var whereSql = ' WHERE 1=1';
    var sqlParams = [];
    if (keyword) {
      whereSql +=
        ' AND (subject LIKE ? OR from_name LIKE ? OR from_mail LIKE ?)';
      var kw = '%' + keyword + '%';
      sqlParams.push(kw, kw, kw);
    }

    // 3. 查总数
    var countRow = await db.queryOne(
      'SELECT COUNT(*) AS total FROM mail_archive' + whereSql,
      sqlParams
    );
    var total =
      countRow && countRow.total != null ? Number(countRow.total) : 0;

    // 4. 查分页数据（received_at 降序）
    var items = await db.queryAll(
      'SELECT message_id, subject, from_name, from_mail, received_at, ' +
        'body_preview, labels, processing_status FROM mail_archive' +
        whereSql +
        ' ORDER BY received_at DESC LIMIT ? OFFSET ?',
      sqlParams.concat([size, offset])
    );

    return {
      ok: true,
      data: {
        archives: Array.isArray(items) ? items : [],
        total: total,
        page: page,
        size: size,
      },
    };
  } catch (err) {
    logger.error(
      'get_archives: 查询归档列表异常 err=' +
        (err && err.message ? err.message : err)
    );
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
