'use strict';

/**
 * WorkBuddy 妙搭数据库访问层。
 * 通过妙搭 OpenAPI 执行 SQL（MySQL 兼容语法）。
 *
 * 注意：妙搭 OpenAPI 的确切调用方式（鉴权头、请求/响应格式）需在妙搭环境验证。
 * 当前实现基于常见模式：
 *   - 鉴权：Authorization: Bearer <MIAODA_OPENAPI_KEY>
 *   - 请求：POST {MIAODA_API_BASE}/v1/apps/{MIAODA_APP_ID}/db/execute
 *   - body：{ sql, params }
 *   - 响应：{ code: 0, data: { rows: [...] / affectedRows / insertId } }
 * 若实际格式不同，请调整 _request 内的解析逻辑。
 */

const axios = require('axios');

/** 妙达 OpenAPI 基础地址（可按环境覆盖） */
const MIAODA_API_BASE =
  process.env.MIAODA_API_BASE || 'https://miaoda.feishu.cn/open-apis';

/**
 * 获取妙搭应用 ID。
 * @returns {string} MIAODA_APP_ID
 * @throws {Error} 未设置 MIAODA_APP_ID 时抛出
 */
function _getAppId() {
  const appId = process.env.MIAODA_APP_ID;
  if (!appId) {
    throw new Error('db: 未设置环境变量 MIAODA_APP_ID');
  }
  return appId;
}

/**
 * 获取妙搭 OpenAPI 密钥。
 * @returns {string} MIAODA_OPENAPI_KEY
 * @throws {Error} 未设置 MIAODA_OPENAPI_KEY 时抛出
 */
function _getApiKey() {
  const key = process.env.MIAODA_OPENAPI_KEY;
  if (!key) {
    throw new Error('db: 未设置环境变量 MIAODA_OPENAPI_KEY');
  }
  return key;
}

/**
 * 发送 SQL 执行请求到妙搭 OpenAPI。
 * @param {string} sql - SQL 语句（可含 ? 占位符）
 * @param {Array} [params=[]] - 参数数组，与 ? 一一对应
 * @returns {Promise<Object>} 妙搭返回的 data 对象
 * @throws {Error} HTTP 失败或业务 code 非 0 时抛出含 message + sql 的 Error
 */
async function _request(sql, params) {
  if (params === undefined) params = [];
  const appId = _getAppId();
  const apiKey = _getApiKey();
  const url = `${MIAODA_API_BASE}/v1/apps/${appId}/db/execute`;
  try {
    const resp = await axios.post(
      url,
      { sql: sql, params: params },
      {
        headers: {
          'Authorization': `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
        },
        timeout: 15000,
      }
    );
    const body = resp.data || {};
    // 业务码非 0 视为失败
    if (body.code !== undefined && body.code !== 0) {
      const msg = body.msg || body.message || JSON.stringify(body);
      throw new Error(`db: SQL 执行失败 code=${body.code} msg=${msg}; SQL: ${sql}`);
    }
    return body.data || {};
  } catch (err) {
    // axios 错误（网络/超时/非 2xx）补充上下文后抛出
    if (err.response) {
      const status = err.response.status;
      const body = err.response.data;
      const msg = (body && (body.msg || body.message)) || JSON.stringify(body);
      throw new Error(`db: HTTP ${status} msg=${msg}; SQL: ${sql}`);
    }
    // 已是带 SQL 上下文的业务错误，直接抛
    if (err.message && err.message.indexOf('SQL:') !== -1) {
      throw err;
    }
    // 其他错误补充 SQL 上下文
    throw new Error(`db: ${err.message}; SQL: ${sql}`);
  }
}

/**
 * 执行 SQL 语句（INSERT/UPDATE/DELETE/DDL 等）。
 * @param {string} sql - SQL 语句（可含 ? 占位符）
 * @param {Array} [params=[]] - 参数数组
 * @returns {Promise<Object>} 执行结果（含 affectedRows / insertId 等）
 * @throws {Error} SQL 错误抛出含 message + sql 的 Error
 */
async function execute(sql, params) {
  if (params === undefined) params = [];
  return _request(sql, params);
}

/**
 * 查询单行记录。
 * @param {string} sql - SELECT SQL（可含 ? 占位符）
 * @param {Array} [params=[]] - 参数数组
 * @returns {Promise<Object|null>} 匹配的单行对象；无结果返回 null
 * @throws {Error} SQL 错误抛出含 message + sql 的 Error
 */
async function queryOne(sql, params) {
  if (params === undefined) params = [];
  const data = await _request(sql, params);
  const rows = data.rows || data.items || data || [];
  return Array.isArray(rows) && rows.length > 0 ? rows[0] : null;
}

/**
 * 查询多行记录。
 * @param {string} sql - SELECT SQL（可含 ? 占位符）
 * @param {Array} [params=[]] - 参数数组
 * @returns {Promise<Array>} 行对象数组；无结果返回 []
 * @throws {Error} SQL 错误抛出含 message + sql 的 Error
 */
async function queryAll(sql, params) {
  if (params === undefined) params = [];
  const data = await _request(sql, params);
  const rows = data.rows || data.items || data || [];
  return Array.isArray(rows) ? rows : [];
}

/**
 * INSERT 便捷方法。构造 INSERT SQL 并执行。
 * @param {string} table - 表名
 * @param {Object} data - 列名到值的映射，如 { col1: 'v1', col2: 2 }
 * @returns {Promise<Object>} 执行结果（含 insertId 等）
 * @throws {Error} 构造或执行失败抛出含 message + table 的 Error
 */
async function insert(table, data) {
  if (!table || typeof table !== 'string') {
    throw new Error(`db.insert: table 参数无效 (table=${table})`);
  }
  if (!data || typeof data !== 'object' || Object.keys(data).length === 0) {
    throw new Error(`db.insert: data 参数无效 (table=${table})`);
  }
  var cols = Object.keys(data);
  var placeholders = cols.map(function () { return '?'; }).join(', ');
  var values = cols.map(function (k) { return data[k]; });
  var sql = `INSERT INTO ${table} (${cols.join(', ')}) VALUES (${placeholders})`;
  return _request(sql, values);
}

/**
 * UPDATE 便捷方法。构造 UPDATE SQL 并执行。
 * @param {string} table - 表名
 * @param {Object} set - SET 列名到值的映射，如 { col1: 'v1' }
 * @param {Object} where - WHERE 列名到值的映射（AND 连接，精确相等），如 { id: 1 }
 * @returns {Promise<Object>} 执行结果（含 affectedRows 等）
 * @throws {Error} 构造或执行失败抛出含 message + table 的 Error
 */
async function update(table, set, where) {
  if (!table || typeof table !== 'string') {
    throw new Error(`db.update: table 参数无效 (table=${table})`);
  }
  if (!set || typeof set !== 'object' || Object.keys(set).length === 0) {
    throw new Error(`db.update: set 参数无效 (table=${table})`);
  }
  if (!where || typeof where !== 'object' || Object.keys(where).length === 0) {
    throw new Error(`db.update: where 参数无效 (table=${table})，UPDATE 必须有 WHERE 条件`);
  }
  var setCols = Object.keys(set);
  var setClause = setCols.map(function (k) { return `${k} = ?`; }).join(', ');
  var setValues = setCols.map(function (k) { return set[k]; });
  var whereCols = Object.keys(where);
  var whereClause = whereCols.map(function (k) { return `${k} = ?`; }).join(' AND ');
  var whereValues = whereCols.map(function (k) { return where[k]; });
  var sql = `UPDATE ${table} SET ${setClause} WHERE ${whereClause}`;
  return _request(sql, setValues.concat(whereValues));
}

module.exports = {
  execute: execute,
  queryOne: queryOne,
  queryAll: queryAll,
  insert: insert,
  update: update,
};
