'use strict';

/**
 * WorkBuddy 飞书邮箱 OpenAPI 客户端。
 * 提供未读邮件列表、邮件详情、标记已读能力。
 *
 * 注意：飞书邮箱 OpenAPI 的确切路径需在妙搭环境验证。
 * 当前路径基于飞书邮箱 v1 API，参考 feishu/notifier.py 里 _extract_message
 * 解析的字段结构（message_id / subject / head_from{name, mail_address} /
 * internal_date / body_preview / label_ids）。
 * 若 OpenAPI 路径不同，请调整 FEISHU_MAIL_API_BASE。
 *
 * 错误处理：401 自动 refresh 后重试一次；其他错误抛出含 status + body 的 Error。
 */

const axios = require('axios');
const oauth = require('./feishu-oauth');

/**
 * 飞书邮箱 API 基础地址（可按环境覆盖）。
 * 默认指向飞书邮箱 v1 API，需在妙搭环境验证。
 */
const FEISHU_MAIL_API_BASE =
  process.env.FEISHU_MAIL_API_BASE || 'https://open.feishu.cn/open-apis/mail/v1';

/** 单次请求超时（毫秒） */
const REQUEST_TIMEOUT = 15000;

/**
 * 构造带 Authorization 头的请求配置。
 * @param {string} method - HTTP 方法（GET/PATCH/POST）
 * @param {string} url - 完整 URL
 * @param {Object} [body] - 请求体（POST/PATCH 时使用）
 * @returns {Promise<Object>} axios 请求配置对象
 */
async function _buildConfig(method, url, body) {
  var token = await oauth.getUserAccessToken();
  var config = {
    method: method,
    url: url,
    headers: {
      'Authorization': `Bearer ${token}`,
    },
    timeout: REQUEST_TIMEOUT,
  };
  if (body !== undefined) {
    config.data = body;
    config.headers['Content-Type'] = 'application/json';
  }
  return config;
}

/**
 * 解析飞书 API 响应，提取 data 字段。
 * @param {Object} resp - axios 响应对象
 * @param {string} url - 请求 URL（用于错误上下文）
 * @returns {Object} 飞书信封中的 data 字段
 * @throws {Error} 业务码非 0 时抛出含 code + msg + url 的 Error
 */
function _parseResponse(resp, url) {
  var body = resp.data || {};
  if (body.code !== undefined && body.code !== 0) {
    throw new Error(
      `feishu-mail: API 失败 code=${body.code} msg=${body.msg || ''}; url=${url}`
    );
  }
  return body.data != null ? body.data : body;
}

/**
 * 将错误包装为含 status + body 上下文的 Error。
 * @param {Error} err - 原始错误
 * @param {string} url - 请求 URL
 * @returns {Error} 包装后的 Error
 */
function _wrapError(err, url) {
  // 已是带 feishu-mail: 前缀的错误，直接返回
  if (err.message && err.message.indexOf('feishu-mail:') !== -1) {
    return err;
  }
  if (err.response) {
    var status = err.response.status;
    var respBody = err.response.data;
    return new Error(
      `feishu-mail: HTTP ${status} body=${JSON.stringify(respBody)}; url=${url}`
    );
  }
  return new Error(`feishu-mail: ${err.message}; url=${url}`);
}

/**
 * 发送带 401 自动重试的请求。
 * @param {string} method - HTTP 方法
 * @param {string} url - 完整 URL
 * @param {Object} [body] - 请求体
 * @returns {Promise<Object>} 飞书 API 响应的 data 字段
 * @throws {Error} 含 status + body 的 Error
 */
async function _request(method, url, body) {
  var config = await _buildConfig(method, url, body);
  try {
    var resp = await axios(config);
    return _parseResponse(resp, url);
  } catch (err) {
    // 401 → 刷新 token 后重试一次
    if (err.response && err.response.status === 401) {
      try {
        await oauth.refreshTokensIfNeeded(true);
      } catch (refreshErr) {
        throw new Error(
          `feishu-mail: token 刷新失败（401 重试）${refreshErr.message}; url=${url}`
        );
      }
      config = await _buildConfig(method, url, body);
      try {
        var resp2 = await axios(config);
        return _parseResponse(resp2, url);
      } catch (retryErr) {
        throw _wrapError(retryErr, url);
      }
    }
    throw _wrapError(err, url);
  }
}

/**
 * 列出未读收件箱邮件。
 * @param {number} [maxResults=50] - 最多返回条数
 * @returns {Promise<Array<string>>} message_id 列表
 * @throws {Error} 含 status + body 的 Error
 */
async function listUnread(maxResults) {
  if (maxResults === undefined) maxResults = 50;
  if (typeof maxResults !== 'number' || maxResults <= 0) {
    throw new Error(`feishu-mail.listUnread: maxResults 参数无效 (maxResults=${maxResults})`);
  }
  var url =
    `${FEISHU_MAIL_API_BASE}/mailboxes/me/messages` +
    `?filter=is_unread&max_results=${maxResults}`;
  var data = await _request('GET', url);
  // 响应可能是 { messages: [...] } 或 { items: [...] }
  var messages = data.messages || data.items || [];
  var ids = [];
  for (var i = 0; i < messages.length; i++) {
    var m = messages[i];
    if (m && m.message_id) {
      ids.push(m.message_id);
    }
  }
  return ids;
}

/**
 * 批量拉取邮件详情。
 * 注意：若飞书邮箱 OpenAPI 支持批量端点，可优化为单次请求；
 * 当前逐封拉取（与 feishu/watch_worker.py 逐封处理逻辑一致）。
 * @param {Array<string>} messageIds - message_id 数组
 * @returns {Promise<Array<Object>>} 邮件对象数组（含 message_id/subject/head_from/internal_date/body_preview 等）
 * @throws {Error} 含 status + body 的 Error
 */
async function getMessages(messageIds) {
  if (!Array.isArray(messageIds)) {
    throw new Error(`feishu-mail.getMessages: messageIds 参数无效 (messageIds=${messageIds})`);
  }
  var results = [];
  for (var i = 0; i < messageIds.length; i++) {
    var mid = messageIds[i];
    var url = `${FEISHU_MAIL_API_BASE}/mailboxes/me/messages/${encodeURIComponent(mid)}`;
    try {
      var data = await _request('GET', url);
      // 响应可能是 { message: {...} } 或裸邮件对象
      var msg = data.message || data;
      results.push(msg);
    } catch (err) {
      // 单封失败不阻塞其余邮件，但向上抛含上下文的错误
      throw new Error(
        `feishu-mail.getMessages: 拉取邮件详情失败 message_id=${mid} cause=${err.message}`
      );
    }
  }
  return results;
}

/**
 * 标记邮件已读。
 * @param {string} messageId - 邮件 message_id
 * @returns {Promise<Object>} 响应结果
 * @throws {Error} 含 status + body 的 Error
 */
async function markAsRead(messageId) {
  if (!messageId || typeof messageId !== 'string') {
    throw new Error(`feishu-mail.markAsRead: messageId 参数无效 (messageId=${messageId})`);
  }
  var url = `${FEISHU_MAIL_API_BASE}/mailboxes/me/messages/${encodeURIComponent(messageId)}`;
  return _request('PATCH', url, { is_unread: false });
}

module.exports = {
  listUnread: listUnread,
  getMessages: getMessages,
  markAsRead: markAsRead,
};
