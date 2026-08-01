'use strict';

/**
 * WorkBuddy 外部操作执行模块。
 * 在审批通过后执行对外动作（发邮件 / 发 IM 通知 / 创建任务），并记录审计日志。
 *
 * 飞书邮箱发信、IM 通知、任务创建为用户级操作，使用 user_access_token 鉴权
 * （通过 feishu-oauth.getUserAccessToken 获取）。
 *
 * 仅依赖 Node.js 内置模块（https/http/url），不依赖任何第三方库。
 *
 * 接口参考：
 *   - 发送邮件：POST /mail/v1/mailboxes/{user_id}/messages/send（user_access_token）
 *   - 发送 IM：POST /im/v1/messages?receive_id_type=chat_id（user_access_token）
 *   - 创建任务：POST /task/v2/tasks（user_access_token）
 *
 * 审计日志写入 external_operations 表（操作类型 / 输入 / 输出 / 时间戳 / 状态）。
 */

const https = require('https');
const http = require('http');
const url = require('url');
const oauth = require('./feishu-oauth');
const db = require('./db');
const logger = require('./logger');
const { FEISHU_OPENAPI_BASE } = require('./constants');

/** 单次请求超时（毫秒） */
const REQUEST_TIMEOUT_MS = 15000;

/** 外部操作审计日志表名 */
const EXTERNAL_OPS_TABLE = 'external_operations';

/** 支持的外部操作类型 */
const ACTION_TYPES = {
  SEND_EMAIL: 'send_email',
  SEND_IM: 'send_im',
  CREATE_TASK: 'create_task',
};

/**
 * 用 Node.js 内置 https/http 模块发送 JSON 请求（支持 GET/POST）。
 * @param {string} method - HTTP 方法（GET/POST）
 * @param {string} requestUrl - 完整请求 URL
 * @param {Object} [body] - 请求体对象（GET 时传 undefined）
 * @param {Object} [headers] - 额外请求头
 * @param {number} [timeoutMs] - 超时毫秒
 * @returns {Promise<Object>} { statusCode, data, raw }，data 为已解析的 JSON
 * @throws {Error} 网络/超时抛出含上下文的 Error
 */
function _httpRequest(method, requestUrl, body, headers, timeoutMs) {
  return new Promise((resolve, reject) => {
    const parsed = url.parse(requestUrl);
    const isHttps = parsed.protocol === 'https:';
    const lib = isHttps ? https : http;
    const finalHeaders = Object.assign({}, headers || {});
    let payload = null;
    if (body !== undefined && body !== null) {
      payload = Buffer.from(JSON.stringify(body), 'utf8');
      finalHeaders['Content-Type'] = finalHeaders['Content-Type'] || 'application/json';
      finalHeaders['Content-Length'] = payload.length;
    }
    const options = {
      method: method,
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
      reject(new Error(`网络请求失败 ${err.message}`));
    });
    if (timeoutMs && timeoutMs > 0) {
      req.setTimeout(timeoutMs, () => {
        req.destroy(new Error(`请求超时 (${timeoutMs}ms)`));
      });
    }
    if (payload) {
      req.write(payload);
    }
    req.end();
  });
}

/**
 * 解析飞书 API 响应信封，提取 data 字段。
 * @param {Object} resp - _httpRequest 返回的 { statusCode, data, raw }
 * @param {string} action - 操作描述（用于错误上下文）
 * @returns {Object} 飞书信封中的 data 字段
 * @throws {Error} HTTP 非 2xx 或业务 code 非 0 时抛出含 code + msg 的 Error
 */
function _parseResp(resp, action) {
  if (resp.statusCode < 200 || resp.statusCode >= 300) {
    const body = resp.data || {};
    const msg = (body && (body.msg || body.message)) || resp.raw || '';
    throw new Error(
      `external_actions: ${action} HTTP ${resp.statusCode} body=${msg}`
    );
  }
  const body = resp.data || {};
  if (body.code !== undefined && body.code !== 0) {
    throw new Error(
      `external_actions: ${action} 失败 code=${body.code} msg=${body.msg || ''}`
    );
  }
  return body.data != null ? body.data : body;
}

/**
 * 当前时间格式化为 'YYYY-MM-DD HH:MM:SS'（用于审计日志时间戳）。
 * @returns {string} 格式化后的时间字符串
 */
function _nowStr() {
  const d = new Date();
  const pad = function (n) {
    return n < 10 ? '0' + n : '' + n;
  };
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

/**
 * 执行外部操作。根据 actionType 分发到对应模块（发邮件 / 发 IM / 创建任务）。
 * 使用 user_access_token 鉴权（内部自动获取）。
 * @param {string} missionId - 关联任务 ID（用于审计日志）
 * @param {string} actionType - 操作类型：send_email / send_im / create_task
 * @param {Object} actionData - 操作输入数据，结构因 actionType 而异：
 *   - send_email: { to, subject, body }
 *   - send_im: { chat_id(或 chatId), card(或 message / cardContent) }
 *   - create_task: { summary(或 title), description, ... }
 * @returns {Promise<Object>} 操作执行结果（对应飞书 API 响应 data）
 * @throws {Error} 参数无效 / token 获取失败 / 不支持的类型 / API 失败时抛出
 */
async function executeExternalAction(missionId, actionType, actionData) {
  if (!missionId) {
    throw new Error('external_actions.executeExternalAction: missionId 参数无效');
  }
  if (!actionType || typeof actionType !== 'string') {
    throw new Error(
      `external_actions.executeExternalAction: actionType 参数无效 (actionType=${actionType})`
    );
  }
  if (!actionData || typeof actionData !== 'object') {
    actionData = {};
  }

  // 获取 user_access_token（邮箱发信 / IM 通知 / 任务创建均为用户级操作）
  let token;
  try {
    token = await oauth.getUserAccessToken();
  } catch (err) {
    throw new Error(
      `external_actions: 获取 user_access_token 失败 ${err.message}`
    );
  }

  // 按类型分发
  if (actionType === ACTION_TYPES.SEND_EMAIL) {
    return sendEmail(
      token,
      actionData.to,
      actionData.subject,
      actionData.body
    );
  }
  if (actionType === ACTION_TYPES.SEND_IM) {
    const chatId = actionData.chat_id || actionData.chatId;
    const cardContent =
      actionData.card || actionData.message || actionData.cardContent;
    return sendIM(token, chatId, cardContent);
  }
  if (actionType === ACTION_TYPES.CREATE_TASK) {
    return createTask(token, actionData);
  }
  throw new Error(
    `external_actions.executeExternalAction: 不支持的操作类型 ${actionType}`
  );
}

/**
 * 通过飞书邮箱发送邮件（使用 user_access_token）。
 * @param {string} token - user_access_token
 * @param {string|string[]} to - 收件人邮箱（单个或数组）
 * @param {string} subject - 邮件主题
 * @param {string} body - 邮件正文（HTML 或纯文本）
 * @returns {Promise<Object>} 发送结果（含 message_id 等）
 * @throws {Error} 参数无效或飞书 API 失败时抛出含上下文的 Error
 */
async function sendEmail(token, to, subject, body) {
  if (!token || typeof token !== 'string') {
    throw new Error('external_actions.sendEmail: token 参数无效');
  }
  if (!to) {
    throw new Error('external_actions.sendEmail: to 参数无效');
  }
  // 收件人归一化为数组
  const toArray = Array.isArray(to) ? to : [to];
  // user_id 使用 'me' 代表当前授权用户（与 feishu-mail.js 的 /mailboxes/me/ 约定一致）
  const requestUrl = `${FEISHU_OPENAPI_BASE}/mail/v1/mailboxes/me/messages/send`;
  const reqBody = {
    to: toArray,
    subject: subject || '(无主题)',
    body: body || '',
    content_type: 'text/html',
  };
  let resp;
  try {
    resp = await _httpRequest(
      'POST',
      requestUrl,
      reqBody,
      { Authorization: `Bearer ${token}` },
      REQUEST_TIMEOUT_MS
    );
  } catch (err) {
    throw new Error(`external_actions: 发送邮件 ${err.message}`);
  }
  return _parseResp(resp, '发送邮件');
}

/**
 * 发送 IM 卡片通知（使用 user_access_token）。
 * 卡片内容包含操作执行结果。
 * @param {string} token - user_access_token
 * @param {string} chatId - 目标群聊 chat_id（oc_ 开头）
 * @param {Object|string} cardContent - 卡片 JSON 对象（发送为 interactive）或纯文本（发送为 text）
 * @returns {Promise<Object>} 发送结果（含 message_id 等）
 * @throws {Error} 参数无效或飞书 API 失败时抛出含上下文的 Error
 */
async function sendIM(token, chatId, cardContent) {
  if (!token || typeof token !== 'string') {
    throw new Error('external_actions.sendIM: token 参数无效');
  }
  if (!chatId || typeof chatId !== 'string') {
    throw new Error(
      `external_actions.sendIM: chatId 参数无效 (chatId=${chatId})`
    );
  }
  // 字符串 → text 消息；对象 → interactive 卡片消息
  let msgType;
  let content;
  if (typeof cardContent === 'string') {
    msgType = 'text';
    content = JSON.stringify({ text: cardContent });
  } else {
    msgType = 'interactive';
    content = JSON.stringify(cardContent || {});
  }
  const requestUrl = `${FEISHU_OPENAPI_BASE}/im/v1/messages?receive_id_type=chat_id`;
  const reqBody = {
    receive_id: chatId,
    msg_type: msgType,
    content: content,
  };
  let resp;
  try {
    resp = await _httpRequest(
      'POST',
      requestUrl,
      reqBody,
      { Authorization: `Bearer ${token}` },
      REQUEST_TIMEOUT_MS
    );
  } catch (err) {
    throw new Error(`external_actions: 发送 IM ${err.message}`);
  }
  return _parseResp(resp, '发送 IM');
}

/**
 * 创建飞书任务（使用 user_access_token）。
 * @param {string} token - user_access_token
 * @param {Object} taskData - 任务数据：{ summary(或 title), description, ... }
 * @returns {Promise<Object>} 创建结果（含 task guid 等）
 * @throws {Error} 参数无效或飞书 API 失败时抛出含上下文的 Error
 */
async function createTask(token, taskData) {
  if (!token || typeof token !== 'string') {
    throw new Error('external_actions.createTask: token 参数无效');
  }
  if (!taskData || typeof taskData !== 'object') {
    throw new Error('external_actions.createTask: taskData 参数无效');
  }
  const requestUrl = `${FEISHU_OPENAPI_BASE}/task/v2/tasks`;
  const reqBody = {
    summary: taskData.summary || taskData.title || 'WorkBuddy 任务',
    description: taskData.description || '',
  };
  let resp;
  try {
    resp = await _httpRequest(
      'POST',
      requestUrl,
      reqBody,
      { Authorization: `Bearer ${token}` },
      REQUEST_TIMEOUT_MS
    );
  } catch (err) {
    throw new Error(`external_actions: 创建任务 ${err.message}`);
  }
  return _parseResp(resp, '创建任务');
}

/**
 * 记录外部操作审计日志到 external_operations 表。
 * 包含操作类型、输入、输出、时间戳、状态。
 * 写表失败只记日志，不抛异常（不阻断主流程）。
 * @param {string} missionId - 关联任务 ID
 * @param {string} actionType - 操作类型
 * @param {Object} actionData - 操作输入
 * @param {Object} result - 操作结果对象，形如 { ok: true, result: {...} } 或 { ok: false, error: '...' }
 * @returns {Promise<void>}
 */
async function recordExternalOperation(missionId, actionType, actionData, result) {
  const ok = !!(result && result.ok);
  const record = {
    mission_id: missionId || '',
    action_type: actionType || '',
    action_data: JSON.stringify(actionData || {}),
    result: JSON.stringify(result || {}),
    status: ok ? 'success' : 'failed',
    created_at: _nowStr(),
  };
  try {
    await db.insert(EXTERNAL_OPS_TABLE, record);
  } catch (err) {
    // 审计日志写失败不阻断主流程
    logger.error(
      `external_actions.recordExternalOperation: 写审计日志失败 mission=${missionId} ` +
      `action=${actionType} err=${err && err.message ? err.message : err}`
    );
  }
}

module.exports = {
  executeExternalAction: executeExternalAction,
  sendEmail: sendEmail,
  sendIM: sendIM,
  createTask: createTask,
  recordExternalOperation: recordExternalOperation,
  ACTION_TYPES: ACTION_TYPES,
};
