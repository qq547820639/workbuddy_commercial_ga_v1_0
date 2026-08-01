'use strict';

/**
 * WorkBuddy 飞书 IM OpenAPI 客户端。
 * 提供交互卡片 / 文本消息发送能力，以及邮件通知、任务到达通知卡片构建器。
 *
 * 仅依赖 Node.js 内置模块（https/http/url），不依赖任何第三方库。
 * token 通过显式参数传入（user_access_token）；未传入时自动通过 feishu-oauth 获取。
 *
 * 飞书 IM API（user_access_token 鉴权）：
 *   - 发消息：POST /im/v1/messages?receive_id_type=chat_id
 *     body: { receive_id, msg_type, content }
 *
 * 错误处理：
 *   - 401（token 过期）：若 token 为自动获取则刷新后重试一次；显式传入则抛出。
 *   - 网络/超时：抛出含 url 上下文的 Error。
 *   - API 业务码非 0：抛出含 code + msg 的 Error。
 *
 * 向后兼容：保留旧调用签名 sendCard(chatId, cardContent) / sendText(chatId, text)，
 *   旧调用不传 token，内部自动获取。
 *
 * 卡片结构参考 feishu/notifier.py 的 build_card。
 */

const https = require('https');
const http = require('http');
const url = require('url');
const oauth = require('./feishu-oauth');
const {
  CARD_TEMPLATE,
  BODY_PREVIEW_LIMIT,
  SUBJECT_TRUNCATE_LIMIT,
} = require('./constants');

/**
 * 飞书 IM API 基础地址（可按环境覆盖）。
 */
const FEISHU_IM_API_BASE =
  process.env.FEISHU_IM_API_BASE || 'https://open.feishu.cn/open-apis';

/** 单次请求超时（毫秒） */
const REQUEST_TIMEOUT_MS = 15000;

/**
 * 用 Node.js 内置 https/http 模块发送 JSON 请求（支持 GET/POST/PATCH）。
 * @param {string} method - HTTP 方法
 * @param {string} requestUrl - 完整请求 URL
 * @param {Object|null} [body] - 请求体对象（GET 时传 null）
 * @param {string} token - user_access_token（Bearer）
 * @param {number} [timeoutMs] - 超时毫秒
 * @returns {Promise<Object>} { statusCode, data, raw }
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
      reject(new Error(`feishu-im: 网络请求失败 ${err.message}; url=${requestUrl}`));
    });
    if (timeoutMs && timeoutMs > 0) {
      req.setTimeout(timeoutMs, () => {
        req.destroy(new Error(`feishu-im: 请求超时 (${timeoutMs}ms); url=${requestUrl}`));
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
    throw new Error(`feishu-im: token 无效或过期 (HTTP 401); url=${requestUrl}`);
  }
  if (resp.statusCode < 200 || resp.statusCode >= 300) {
    const body = resp.data || {};
    const msg =
      (body && typeof body === 'object' && (body.msg || body.message)) ||
      (typeof resp.raw === 'string' ? resp.raw : JSON.stringify(resp.raw || {}));
    throw new Error(`feishu-im: HTTP ${resp.statusCode} body=${msg}; url=${requestUrl}`);
  }
  const body = resp.data || {};
  if (body && typeof body === 'object' && body.code !== undefined && body.code !== 0) {
    throw new Error(
      `feishu-im: API 失败 code=${body.code} msg=${body.msg || ''}; url=${requestUrl}`
    );
  }
  return body && body.data != null ? body.data : body;
}

/**
 * 发送带 401 自动重试的请求（仅当 token 为自动获取时重试）。
 * @param {string} pathWithQuery - 路径 + 查询串（拼到 FEISHU_IM_API_BASE 后）
 * @param {Object} body - 请求体
 * @param {string} [token] - 显式 user_access_token
 * @returns {Promise<Object>} 飞书 API 响应的 data 字段
 */
async function _call(pathWithQuery, body, token) {
  const explicit = !!(token && typeof token === 'string');
  let accessToken = await _resolveToken(token);
  const fullUrl = FEISHU_IM_API_BASE + pathWithQuery;
  let resp = await _httpsRequest('POST', fullUrl, body, accessToken, REQUEST_TIMEOUT_MS);
  if (resp.statusCode === 401 && !explicit) {
    try {
      await oauth.refreshTokensIfNeeded(true);
    } catch (refreshErr) {
      throw new Error(
        `feishu-im: token 刷新失败（401 重试）${refreshErr.message}; url=${fullUrl}`
      );
    }
    accessToken = await _resolveToken(undefined);
    resp = await _httpsRequest('POST', fullUrl, body, accessToken, REQUEST_TIMEOUT_MS);
  }
  return _parseResp(resp, fullUrl);
}

/**
 * 从邮件数据中提取 message dict。
 * 兼容三种形态（与 feishu/notifier.py _extract_message 一致）：
 *   - 裸 data：{ message: {...} }
 *   - json 信封：{ ok: true, data: { message: {...} } }
 *   - 裸 message：{ message_id: ... }
 * @param {Object} mailData - 邮件数据
 * @returns {Object} 邮件 message 对象
 */
function _extractMessage(mailData) {
  if (!mailData || typeof mailData !== 'object') {
    return {};
  }
  let data = mailData.data;
  if (data && typeof data === 'object') {
    mailData = data;
  }
  const msg = mailData.message;
  if (msg && typeof msg === 'object') {
    return msg;
  }
  return mailData;
}

/**
 * internal_date（毫秒级 epoch 字符串）转本地可读时间 'YYYY-MM-DD HH:MM:SS'。
 * 与 feishu/notifier.py _fmt_time 一致。
 * @param {string|number} internalDate - 毫秒级 epoch
 * @returns {string} 格式化后的时间字符串
 */
function _fmtTime(internalDate) {
  try {
    const ms = parseInt(internalDate, 10);
    if (isNaN(ms)) {
      return internalDate ? String(internalDate) : '未知';
    }
    const d = new Date(ms);
    const pad = (n) => (n < 10 ? '0' + n : '' + n);
    return (
      d.getFullYear() + '-' +
      pad(d.getMonth() + 1) + '-' +
      pad(d.getDate()) + ' ' +
      pad(d.getHours()) + ':' +
      pad(d.getMinutes()) + ':' +
      pad(d.getSeconds())
    );
  } catch (e) {
    return internalDate ? String(internalDate) : '未知';
  }
}

/**
 * 截断文本，超出加省略号。
 * @param {string} text - 原始文本
 * @param {number} limit - 最大长度
 * @returns {string} 截断后的文本
 */
function _truncate(text, limit) {
  if (!text) {
    return '';
  }
  const s = String(text);
  return s.length <= limit ? s : s.slice(0, limit) + '…';
}

/**
 * 从邮件详情构造 Card 2.0 交互卡片 JSON（新邮件通知）。
 * 结构参考 feishu/notifier.py build_card：
 *   header — "新邮件通知" + 主题副标题（蓝色头部）
 *   body   — 发件人 / 时间 / 分隔线 / 正文预览
 * @param {Object} mailData - 邮件详情（含 message 信封或裸 message）
 * @returns {Object} Card 2.0 交互卡片 JSON
 */
function buildMailCard(mailData) {
  const msg = _extractMessage(mailData);
  const subject = msg.subject || '(无主题)';
  const headFrom = msg.head_from || {};
  const fromName = headFrom.name || msg.from_name || '未知发件人';
  const fromMail = headFrom.mail_address || msg.from_mail || '';
  const bodyPreview = _truncate(msg.body_preview, BODY_PREVIEW_LIMIT);
  const timeStr = _fmtTime(msg.internal_date);

  let fromLine = '**发件人**\n' + fromName;
  if (fromMail) {
    fromLine += ' <' + fromMail + '>';
  }

  const elements = [
    { tag: 'div', text: { tag: 'lark_md', content: fromLine } },
    { tag: 'div', text: { tag: 'lark_md', content: '**时间**\n' + timeStr } },
    { tag: 'hr' },
    {
      tag: 'markdown',
      content: bodyPreview
        ? '**正文预览**\n' + bodyPreview
        : '**正文预览**\n(无预览)',
    },
  ];

  // 深拷贝模板，避免修改共享常量
  const card = JSON.parse(JSON.stringify(CARD_TEMPLATE));
  card.header.title.content = '新邮件通知';
  card.header.subtitle.content = _truncate(subject, SUBJECT_TRUNCATE_LIMIT);
  card.body.elements = elements;
  return card;
}

/**
 * 构造任务到达通知 Card 2.0 交互卡片 JSON。
 * 蓝色头部，标题"任务到达通知"，含团队 / 任务标题 / 风险等级 / 操作按钮。
 * @param {Object} missionData - 任务数据，可含 team_key/title/risk_level/objective/id 等
 * @returns {Object} Card 2.0 交互卡片 JSON
 */
function buildTaskCard(missionData) {
  const data = missionData || {};
  const teamKey = data.team_key || data.teamKey || '';
  const title = data.title || '(无标题)';
  const riskLevel = data.risk_level || data.riskLevel || 'unknown';
  const objective = data.objective || '';
  const missionId = data.id != null ? String(data.id) : '';

  const elements = [
    { tag: 'div', text: { tag: 'lark_md', content: '**所属团队**\n' + (teamKey || '未分配') } },
    { tag: 'div', text: { tag: 'lark_md', content: '**任务标题**\n' + title } },
    { tag: 'div', text: { tag: 'lark_md', content: '**风险等级**\n' + riskLevel } },
  ];

  if (objective) {
    elements.push({ tag: 'hr' });
    elements.push({
      tag: 'markdown',
      content: '**目标**\n' + _truncate(objective, BODY_PREVIEW_LIMIT),
    });
  }

  // 操作按钮：查看任务 / 开始处理
  elements.push({
    tag: 'action',
    actions: [
      {
        tag: 'button',
        text: { tag: 'plain_text', content: '查看任务' },
        type: 'primary',
        value: { action: 'view_mission', mission_id: missionId },
      },
      {
        tag: 'button',
        text: { tag: 'plain_text', content: '开始处理' },
        type: 'default',
        value: { action: 'start_mission', mission_id: missionId },
      },
    ],
  });

  // 深拷贝模板，避免修改共享常量
  const card = JSON.parse(JSON.stringify(CARD_TEMPLATE));
  card.header.title.content = '任务到达通知';
  card.header.subtitle.content = _truncate(title, SUBJECT_TRUNCATE_LIMIT);
  card.body.elements = elements;
  return card;
}

/**
 * 发送交互卡片到指定群聊。
 * @param {string} [token] - user_access_token（可省略，自动获取）
 * @param {string} chatId - 目标群聊 chat_id（oc_ 开头）
 * @param {Object} cardContent - Card 2.0 交互卡片 JSON 对象
 * @returns {Promise<Object>} 发送结果（含 message_id 等）
 * @throws {Error} 含 status + body 的 Error
 */
async function sendCard(token, chatId, cardContent) {
  // 向后兼容旧签名 sendCard(chatId, cardContent)（两参数）
  if (arguments.length === 2) {
    cardContent = chatId;
    chatId = token;
    token = undefined;
  }
  if (!chatId || typeof chatId !== 'string') {
    throw new Error(`feishu-im.sendCard: chatId 参数无效 (chatId=${chatId})`);
  }
  if (!cardContent || typeof cardContent !== 'object') {
    throw new Error(`feishu-im.sendCard: cardContent 参数无效 (chatId=${chatId})`);
  }
  const body = {
    receive_id: chatId,
    msg_type: 'interactive',
    content: JSON.stringify(cardContent),
  };
  return _call('/im/v1/messages?receive_id_type=chat_id', body, token);
}

/**
 * 发送文本消息到指定群聊。
 * @param {string} [token] - user_access_token（可省略，自动获取）
 * @param {string} chatId - 目标群聊 chat_id（oc_ 开头）
 * @param {string} text - 文本内容
 * @returns {Promise<Object>} 发送结果（含 message_id 等）
 * @throws {Error} 含 status + body 的 Error
 */
async function sendText(token, chatId, text) {
  // 向后兼容旧签名 sendText(chatId, text)（两参数）
  if (arguments.length === 2) {
    text = chatId;
    chatId = token;
    token = undefined;
  }
  if (!chatId || typeof chatId !== 'string') {
    throw new Error(`feishu-im.sendText: chatId 参数无效 (chatId=${chatId})`);
  }
  if (text == null || typeof text !== 'string') {
    throw new Error(`feishu-im.sendText: text 参数无效 (chatId=${chatId})`);
  }
  const body = {
    receive_id: chatId,
    msg_type: 'text',
    content: JSON.stringify({ text: text }),
  };
  return _call('/im/v1/messages?receive_id_type=chat_id', body, token);
}

module.exports = {
  sendCard: sendCard,
  sendText: sendText,
  buildMailCard: buildMailCard,
  buildTaskCard: buildTaskCard,
};
