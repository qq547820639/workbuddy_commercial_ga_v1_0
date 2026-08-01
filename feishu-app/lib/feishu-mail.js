'use strict';

/**
 * WorkBuddy 飞书邮箱 OpenAPI 客户端。
 * 提供未读邮件列表、邮件详情、邮箱信息、标记已读能力。
 *
 * 仅依赖 Node.js 内置模块（https/http/url），不依赖任何第三方库。
 * token 通过显式参数传入（user_access_token）；未传入时自动通过 feishu-oauth 获取。
 *
 * 飞书邮箱 v1 API（user_access_token 鉴权，user_id 默认 "me" 代表当前用户）：
 *   - 列未读：GET /mail/v1/mailboxes/{user_id}/messages?filter=is_unread:true
 *   - 邮件详情：GET /mail/v1/mailboxes/{user_id}/messages/{message_id}
 *   - 邮箱信息：GET /mail/v1/mailboxes/{user_id}
 *   - 标记已读：PATCH /mail/v1/mailboxes/{user_id}/messages/{message_id} { is_unread:false }
 *
 * 错误处理：
 *   - 401（token 过期）：若 token 为自动获取则刷新后重试一次；显式传入则抛出。
 *   - 网络/超时：抛出含 url 上下文的 Error。
 *   - API 业务码非 0：抛出含 code + msg 的 Error。
 *
 * 向后兼容：保留旧调用签名（listUnread(maxResults) / getMessages(messageIds) /
 *   markAsRead(messageId)），旧调用不传 token，内部自动获取。
 */

const https = require('https');
const http = require('http');
const url = require('url');
const oauth = require('./feishu-oauth');

/**
 * 飞书邮箱 API 基础地址（可按环境覆盖）。
 * 默认指向飞书邮箱 v1 API，需在妙搭环境验证。
 */
const FEISHU_MAIL_API_BASE =
  process.env.FEISHU_MAIL_API_BASE || 'https://open.feishu.cn/open-apis/mail/v1';

/** 单次请求超时（毫秒） */
const REQUEST_TIMEOUT_MS = 15000;

/**
 * 用 Node.js 内置 https/http 模块发送 JSON 请求（支持 GET/POST/PATCH）。
 * @param {string} method - HTTP 方法（GET/POST/PATCH）
 * @param {string} requestUrl - 完整请求 URL
 * @param {Object|null} [body] - 请求体对象（GET 时传 null）
 * @param {string} token - user_access_token（Bearer）
 * @param {number} [timeoutMs] - 超时毫秒
 * @returns {Promise<Object>} { statusCode, data, raw }，data 为已解析 JSON（解析失败为原始字符串）
 * @throws {Error} 网络/超时抛出含 url 的 Error
 */
function _httpsRequest(method, requestUrl, body, token, timeoutMs) {
  return new Promise((resolve, reject) => {
    const parsed = url.parse(requestUrl);
    const isHttps = parsed.protocol === 'https:';
    const lib = isHttps ? https : http;
    const headers = { Authorization: `Bearer ${token}` };
    let payload = null;
    if (body !== undefined && body !== null) {
      payload = Buffer.from(JSON.stringify(body), 'utf8');
      headers['Content-Type'] = 'application/json';
      headers['Content-Length'] = payload.length;
    }
    const options = {
      method: method,
      hostname: parsed.hostname,
      port: parsed.port || (isHttps ? 443 : 80),
      path: (parsed.pathname || '') + (parsed.search || ''),
      headers: headers,
    };
    const req = lib.request(options, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
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
      reject(new Error(`feishu-mail: 网络请求失败 ${err.message}; url=${requestUrl}`));
    });
    if (timeoutMs && timeoutMs > 0) {
      req.setTimeout(timeoutMs, () => {
        req.destroy(new Error(`feishu-mail: 请求超时 (${timeoutMs}ms); url=${requestUrl}`));
      });
    }
    if (payload) req.write(payload);
    req.end();
  });
}

/**
 * 解析 user_access_token。显式传入则直接使用，否则通过 oauth 自动获取。
 * @param {string} [token] - 显式 user_access_token
 * @returns {Promise<string>} 有效的 user_access_token
 * @throws {Error} 自动获取失败抛出含上下文的 Error
 */
async function _resolveToken(token) {
  if (token && typeof token === 'string') {
    return token;
  }
  return oauth.getUserAccessToken();
}

/**
 * 解析飞书 API 响应，提取 data 字段。
 * @param {Object} resp - _httpsRequest 返回的 { statusCode, data, raw }
 * @param {string} requestUrl - 请求 URL（用于错误上下文）
 * @returns {Object} 飞书信封中的 data 字段
 * @throws {Error} HTTP 非 2xx 或业务 code 非 0 时抛出含 status + msg + url 的 Error
 */
function _parseResp(resp, requestUrl) {
  if (resp.statusCode === 401) {
    throw new Error(`feishu-mail: token 无效或过期 (HTTP 401); url=${requestUrl}`);
  }
  if (resp.statusCode < 200 || resp.statusCode >= 300) {
    const body = resp.data || {};
    const msg =
      (body && typeof body === 'object' && (body.msg || body.message)) ||
      (typeof resp.raw === 'string' ? resp.raw : JSON.stringify(resp.raw || {}));
    throw new Error(`feishu-mail: HTTP ${resp.statusCode} body=${msg}; url=${requestUrl}`);
  }
  const body = resp.data || {};
  if (body && typeof body === 'object' && body.code !== undefined && body.code !== 0) {
    throw new Error(
      `feishu-mail: API 失败 code=${body.code} msg=${body.msg || ''}; url=${requestUrl}`
    );
  }
  return body && body.data != null ? body.data : body;
}

/**
 * 发送带 401 自动重试的请求（仅当 token 为自动获取时重试）。
 * @param {string} method - HTTP 方法
 * @param {string} pathWithQuery - 路径 + 查询串（拼到 FEISHU_MAIL_API_BASE 后）
 * @param {Object|null} [body] - 请求体
 * @param {string} [token] - 显式 user_access_token
 * @returns {Promise<Object>} 飞书 API 响应的 data 字段
 * @throws {Error} 含 status + body 的 Error
 */
async function _call(method, pathWithQuery, body, token) {
  const explicit = !!(token && typeof token === 'string');
  let accessToken = await _resolveToken(token);
  const fullUrl = FEISHU_MAIL_API_BASE + pathWithQuery;
  let resp = await _httpsRequest(method, fullUrl, body, accessToken, REQUEST_TIMEOUT_MS);
  // 401 且 token 为自动获取：刷新后重试一次
  if (resp.statusCode === 401 && !explicit) {
    try {
      await oauth.refreshTokensIfNeeded(true);
    } catch (refreshErr) {
      throw new Error(
        `feishu-mail: token 刷新失败（401 重试）${refreshErr.message}; url=${fullUrl}`
      );
    }
    accessToken = await _resolveToken(undefined);
    resp = await _httpsRequest(method, fullUrl, body, accessToken, REQUEST_TIMEOUT_MS);
  }
  return _parseResp(resp, fullUrl);
}

/**
 * 列出未读收件箱邮件。
 * @param {string} [token] - user_access_token（可省略，自动获取）
 * @param {number} [maxResults=50] - 最多返回条数
 * @returns {Promise<Array<string>>} message_id 列表
 * @throws {Error} 含 status + body 的 Error
 */
async function listUnread(token, maxResults) {
  // 向后兼容旧签名 listUnread(maxResults)
  if (typeof token === 'number') {
    maxResults = token;
    token = undefined;
  }
  if (maxResults === undefined) maxResults = 50;
  if (typeof maxResults !== 'number' || maxResults <= 0) {
    throw new Error(`feishu-mail.listUnread: maxResults 参数无效 (maxResults=${maxResults})`);
  }
  const data = await _call(
    'GET',
    `/mailboxes/me/messages?filter=is_unread:true&max_results=${maxResults}`,
    null,
    token
  );
  const messages = data.messages || data.items || [];
  const ids = [];
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i];
    if (m && m.message_id) {
      ids.push(m.message_id);
    }
  }
  return ids;
}

/**
 * 批量拉取邮件详情（逐封拉取）。
 * @param {string} [token] - user_access_token（可省略，自动获取）
 * @param {Array<string>} messageIds - message_id 数组
 * @returns {Promise<Array<Object>>} 邮件对象数组（含 message_id/subject/head_from/internal_date/body_preview 等）
 * @throws {Error} 含 message_id + cause 的 Error
 */
async function getMessages(token, messageIds) {
  // 向后兼容旧签名 getMessages(messageIds)
  if (Array.isArray(token)) {
    messageIds = token;
    token = undefined;
  }
  if (!Array.isArray(messageIds)) {
    throw new Error(
      `feishu-mail.getMessages: messageIds 参数无效 (messageIds=${messageIds})`
    );
  }
  const results = [];
  for (let i = 0; i < messageIds.length; i++) {
    const mid = messageIds[i];
    try {
      const data = await _call(
        'GET',
        `/mailboxes/me/messages/${encodeURIComponent(mid)}`,
        null,
        token
      );
      // 响应可能是 { message: {...} } 或裸邮件对象
      results.push(data.message || data);
    } catch (err) {
      throw new Error(
        `feishu-mail.getMessages: 拉取邮件详情失败 message_id=${mid} cause=${err.message}`
      );
    }
  }
  return results;
}

/**
 * 获取当前用户邮箱信息。
 * @param {string} [token] - user_access_token（可省略，自动获取）
 * @returns {Promise<Object>} 邮箱信息对象
 * @throws {Error} 含 status + body 的 Error
 */
async function getMailboxInfo(token) {
  return _call('GET', '/mailboxes/me', null, token);
}

/**
 * 标记邮件已读。
 * @param {string} [token] - user_access_token（可省略，自动获取）
 * @param {string} messageId - 邮件 message_id
 * @returns {Promise<Object>} 响应结果
 * @throws {Error} 含 status + body 的 Error
 */
async function markAsRead(token, messageId) {
  // 向后兼容旧签名 markAsRead(messageId)（单参数）
  if (arguments.length === 1) {
    messageId = token;
    token = undefined;
  }
  if (!messageId || typeof messageId !== 'string') {
    throw new Error(
      `feishu-mail.markAsRead: messageId 参数无效 (messageId=${messageId})`
    );
  }
  return _call(
    'PATCH',
    `/mailboxes/me/messages/${encodeURIComponent(messageId)}`,
    { is_unread: false },
    token
  );
}

module.exports = {
  listUnread: listUnread,
  getMessages: getMessages,
  getMailboxInfo: getMailboxInfo,
  markAsRead: markAsRead,
};
