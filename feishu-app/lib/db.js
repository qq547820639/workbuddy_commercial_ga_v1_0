'use strict';

/**
 * WorkBuddy 妙搭数据库访问层。
 * 通过妙搭 OpenAPI 执行 SQL（MySQL 兼容语法）。
 *
 * 仅依赖 Node.js 内置模块（https/http/url），不依赖任何第三方库。
 *
 * 提供两类方法：
 *   1. 标准 CRUD：query / insert / update / selectOne / selectMany
 *   2. 兼容方法（供现有 functions 与 lib 调用）：execute / queryOne / queryAll
 *
 * 妙搭 OpenAPI 调用约定（基于常见模式，需在妙搭环境验证）：
 *   - 鉴权：Authorization: Bearer <MIAODA_OPENAPI_KEY>
 *   - 请求：POST {MIAODA_API_BASE}/v1/apps/{MIAODA_APP_ID}/db/execute
 *   - body：{ sql, params }
 *   - 响应：{ code: 0, data: { rows: [...] / affectedRows / insertId } }
 * 若实际格式不同，请调整 _parseResponse 内的解析逻辑。
 */

const https = require('https');
const http = require('http');
const url = require('url');

/** 妙搭 OpenAPI 基础地址（可按环境覆盖） */
const MIAODA_API_BASE =
  process.env.MIAODA_API_BASE || 'https://miaoda.feishu.cn/open-apis';

/** 单次请求超时（毫秒） */
const REQUEST_TIMEOUT_MS = 15000;

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
 * 用 Node.js 内置 https/http 模块发送 JSON POST 请求。
 * @param {string} requestUrl - 完整请求 URL
 * @param {Object} body - 请求体对象（将 JSON 序列化）
 * @param {Object} headers - 额外请求头
 * @param {number} timeoutMs - 超时毫秒
 * @returns {Promise<Object>} { statusCode, data }，data 为已解析的 JSON
 * @throws {Error} 网络/超时/非 2xx 抛出含上下文的 Error
 */
function _httpPost(requestUrl, body, headers, timeoutMs) {
  return new Promise((resolve, reject) => {
    const parsed = url.parse(requestUrl);
    const isHttps = parsed.protocol === 'https:';
    const lib = isHttps ? https : http;
    const payload = Buffer.from(JSON.stringify(body || {}), 'utf8');
    const finalHeaders = Object.assign(
      {
        'Content-Type': 'application/json',
        'Content-Length': payload.length,
      },
      headers || {}
    );
    const options = {
      method: 'POST',
      hostname: parsed.hostname,
      port: parsed.port || (isHttps ? 443 : 80),
      path: (parsed.pathname || '') + (parsed.search || ''),
      headers: finalHeaders,
    };
    const req = lib.request(options, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        const raw = Buffer.concat(chunks).toString('utf8');
        let parsedBody;
        try {
          parsedBody = raw ? JSON.parse(raw) : {};
        } catch (e) {
          parsedBody = raw;
        }
        resolve({ statusCode: res.statusCode, data: parsedBody, raw: raw });
      });
    });
    req.on('error', (err) => {
      reject(new Error(`db: 网络请求失败 ${err.message}`));
    });
    if (timeoutMs && timeoutMs > 0) {
      req.setTimeout(timeoutMs, () => {
        req.destroy(new Error(`db: 请求超时 (${timeoutMs}ms)`));
      });
    }
    req.write(payload);
    req.end();
  });
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
  const requestUrl = `${MIAODA_API_BASE}/v1/apps/${appId}/db/execute`;
  let resp;
  try {
    resp = await _httpPost(
      requestUrl,
      { sql: sql, params: params },
      { Authorization: `Bearer ${apiKey}` },
      REQUEST_TIMEOUT_MS
    );
  } catch (err) {
    // 网络错误补充 SQL 上下文
    throw new Error(`db: ${err.message}; SQL: ${sql}`);
  }
  // HTTP 非 2xx 视为失败
  if (resp.statusCode < 200 || resp.statusCode >= 300) {
    const body = resp.data || {};
    const msg = (body && (body.msg || body.message)) || resp.raw || '';
    throw new Error(
      `db: HTTP ${resp.statusCode} msg=${msg}; SQL: ${sql}`
    );
  }
  const body = resp.data || {};
  // 业务码非 0 视为失败
  if (body.code !== undefined && body.code !== 0) {
    const msg = body.msg || body.message || JSON.stringify(body);
    throw new Error(`db: SQL 执行失败 code=${body.code} msg=${msg}; SQL: ${sql}`);
  }
  return body.data || {};
}

/**
 * 从妙搭返回的 data 中提取行数组。
 * 兼容 { rows: [...] } / { items: [...] } / 裸数组 三种形态。
 * @param {Object} data - 妙搭 data 对象
 * @returns {Array} 行对象数组
 */
function _extractRows(data) {
  if (Array.isArray(data)) {
    return data;
  }
  const rows = data.rows || data.items || data.list || [];
  return Array.isArray(rows) ? rows : [];
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
 * 执行 SELECT 查询并返回多行记录。
 * @param {string} sql - SELECT SQL（可含 ? 占位符）
 * @param {Array} [params=[]] - 参数数组
 * @returns {Promise<Array>} 行对象数组；无结果返回 []
 * @throws {Error} SQL 错误抛出含 message + sql 的 Error
 */
async function query(sql, params) {
  if (params === undefined) params = [];
  const data = await _request(sql, params);
  return _extractRows(data);
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
  const rows = _extractRows(data);
  return rows.length > 0 ? rows[0] : null;
}

/**
 * 查询多行记录（query 的别名，向后兼容）。
 * @param {string} sql - SELECT SQL（可含 ? 占位符）
 * @param {Array} [params=[]] - 参数数组
 * @returns {Promise<Array>} 行对象数组；无结果返回 []
 * @throws {Error} SQL 错误抛出含 message + sql 的 Error
 */
async function queryAll(sql, params) {
  return query(sql, params);
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
  const cols = Object.keys(data);
  const placeholders = cols.map(() => '?').join(', ');
  const values = cols.map((k) => data[k]);
  const sql = `INSERT INTO ${table} (${cols.join(', ')}) VALUES (${placeholders})`;
  return _request(sql, values);
}

/**
 * UPDATE 便捷方法。按主键 id 更新记录。
 * @param {string} table - 表名
 * @param {string|number} id - 主键值（列名固定为 id）
 * @param {Object} data - SET 列名到值的映射，如 { col1: 'v1' }
 * @returns {Promise<Object>} 执行结果（含 affectedRows 等）
 * @throws {Error} 构造或执行失败抛出含 message + table 的 Error
 */
async function update(table, id, data) {
  if (!table || typeof table !== 'string') {
    throw new Error(`db.update: table 参数无效 (table=${table})`);
  }
  if (id === undefined || id === null) {
    throw new Error(`db.update: id 参数无效 (table=${table})`);
  }
  if (!data || typeof data !== 'object' || Object.keys(data).length === 0) {
    throw new Error(`db.update: data 参数无效 (table=${table})`);
  }
  const setCols = Object.keys(data);
  const setClause = setCols.map((k) => `${k} = ?`).join(', ');
  const setValues = setCols.map((k) => data[k]);
  const sql = `UPDATE ${table} SET ${setClause} WHERE id = ?`;
  return _request(sql, setValues.concat([id]));
}

/**
 * 按条件查询单条记录。
 * @param {string} table - 表名
 * @param {Object} conditions - WHERE 列名到值的映射（AND 连接，精确相等），如 { id: 1 }
 * @returns {Promise<Object|null>} 匹配的单行对象；无结果返回 null
 * @throws {Error} 构造或执行失败抛出含 message + table 的 Error
 */
async function selectOne(table, conditions) {
  if (!table || typeof table !== 'string') {
    throw new Error(`db.selectOne: table 参数无效 (table=${table})`);
  }
  if (!conditions || typeof conditions !== 'object' || Object.keys(conditions).length === 0) {
    throw new Error(`db.selectOne: conditions 参数无效 (table=${table})`);
  }
  const cols = Object.keys(conditions);
  const whereClause = cols.map((k) => `${k} = ?`).join(' AND ');
  const values = cols.map((k) => conditions[k]);
  const sql = `SELECT * FROM ${table} WHERE ${whereClause} LIMIT 1`;
  const data = await _request(sql, values);
  const rows = _extractRows(data);
  return rows.length > 0 ? rows[0] : null;
}

/**
 * 按条件查询多条记录。
 * @param {string} table - 表名
 * @param {Object} conditions - WHERE 列名到值的映射（AND 连接，精确相等）
 * @param {number} [limit=100] - 最多返回条数
 * @returns {Promise<Array>} 行对象数组；无结果返回 []
 * @throws {Error} 构造或执行失败抛出含 message + table 的 Error
 */
async function selectMany(table, conditions, limit) {
  if (!table || typeof table !== 'string') {
    throw new Error(`db.selectMany: table 参数无效 (table=${table})`);
  }
  if (!conditions || typeof conditions !== 'object' || Object.keys(conditions).length === 0) {
    throw new Error(`db.selectMany: conditions 参数无效 (table=${table})`);
  }
  if (limit === undefined) limit = 100;
  if (typeof limit !== 'number' || limit <= 0) {
    throw new Error(`db.selectMany: limit 参数无效 (limit=${limit})`);
  }
  const cols = Object.keys(conditions);
  const whereClause = cols.map((k) => `${k} = ?`).join(' AND ');
  const values = cols.map((k) => conditions[k]);
  const sql = `SELECT * FROM ${table} WHERE ${whereClause} LIMIT ?`;
  return _request(sql, values.concat([limit])).then((data) => _extractRows(data));
}

module.exports = {
  execute: execute,
  query: query,
  queryOne: queryOne,
  queryAll: queryAll,
  insert: insert,
  update: update,
  selectOne: selectOne,
  selectMany: selectMany,
};
