'use strict';

/**
 * WorkBuddy 归档邮件分页查询云函数（HTML 控制台前端 GET 调用）。
 *
 * 支持按 subject 关键字模糊搜索 + 分页。
 *
 * 入口签名说明：妙搭云函数入口约定为 exports.main = async (event, context) => {...}，
 * 具体 event / context 形态需在妙搭环境验证；GET 参数从 event.queryString 读，
 * 兼容直接挂在 event 上的情况。
 *
 * 入参（从 event.queryString 或 event 读）：
 *   - page    页码，默认 1
 *   - size    每页条数，默认 20，钳制到 [1, 100]
 *   - keyword 可选，按 subject 模糊搜索
 *
 * 返回结构：
 *   {
 *     ok: true,
 *     data: {
 *       page: number,
 *       size: number,
 *       total: number,
 *       items: Array<{
 *         message_id, subject, from_name, from_mail,
 *         received_at, body_preview, labels, processing_status
 *       }>
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
  const src = (event && event.queryString) || event || {};
  let page = parseInt(src.page, 10);
  if (isNaN(page) || page < 1) {
    page = 1;
  }
  let size = parseInt(src.size, 10);
  if (isNaN(size) || size < 1) {
    size = DEFAULT_PAGE_SIZE;
  }
  if (size > MAX_PAGE_SIZE) {
    size = MAX_PAGE_SIZE;
  }
  const keyword =
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
    // 1. 解析 page/size，钳制 size 到 [1, 100]
    const { page, size, keyword } = _parseParams(event);

    // 2. 计算偏移
    const offset = (page - 1) * size;

    // 3. 构造 WHERE 条件：keyword 非空时加 subject LIKE
    let whereSql = ' WHERE 1=1';
    const params = [];
    if (keyword) {
      whereSql += ' AND subject LIKE ?';
      params.push('%' + keyword + '%');
    }

    // 4. 查总数
    const countRow = await db.queryOne(
      'SELECT COUNT(*) AS total FROM mail_archive' + whereSql,
      params
    );
    const total =
      countRow && countRow.total != null ? Number(countRow.total) : 0;

    // 5. 查分页数据
    const items = await db.queryAll(
      'SELECT message_id, subject, from_name, from_mail, received_at, ' +
        'body_preview, labels, processing_status FROM mail_archive' +
        whereSql +
        ' ORDER BY received_at DESC LIMIT ? OFFSET ?',
      params.concat([size, offset])
    );

    return {
      ok: true,
      data: {
        page: page,
        size: size,
        total: total,
        items: Array.isArray(items) ? items : [],
      },
    };
  } catch (err) {
    logger.error(
      `list_archives: 查询归档列表异常 err=${err && err.message ? err.message : err}`
    );
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
