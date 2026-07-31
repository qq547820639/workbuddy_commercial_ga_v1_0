'use strict';

/**
 * WorkBuddy 飞书 IM OpenAPI 客户端。
 * 提供交互卡片发送能力。
 *
 * 错误处理：401 自动 refresh 后重试一次；其他错误抛出含 status + body 的 Error。
 * 卡片结构参考 feishu/notifier.py 的 build_card。
 */

const axios = require('axios');
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
const REQUEST_TIMEOUT = 15000;

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
  // json 信封
  var data = mailData.data;
  if (data && typeof data === 'object') {
    mailData = data;
  }
  // data 包了一层 message，或本身就是裸 message
  var msg = mailData.message;
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
    var ms = parseInt(internalDate, 10);
    if (isNaN(ms)) {
      return internalDate ? String(internalDate) : '未知';
    }
    var d = new Date(ms);
    var pad = function (n) {
      return n < 10 ? '0' + n : '' + n;
    };
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
  var s = String(text);
  return s.length <= limit ? s : s.slice(0, limit) + '…';
}

/**
 * 从邮件详情构造 Card 2.0 交互卡片 JSON。
 * 结构参考 feishu/notifier.py build_card：
 *   header — "新邮件" + 主题副标题
 *   body   — 发件人 / 时间 / 分隔线 / 正文预览
 * @param {Object} mailData - 邮件详情（含 message 信封或裸 message）
 * @returns {Object} Card 2.0 交互卡片 JSON
 */
function buildMailCard(mailData) {
  var msg = _extractMessage(mailData);
  var subject = msg.subject || '(无主题)';
  var headFrom = msg.head_from || {};
  var fromName = headFrom.name || '未知发件人';
  var fromMail = headFrom.mail_address || '';
  var bodyPreview = _truncate(msg.body_preview, BODY_PREVIEW_LIMIT);
  var timeStr = _fmtTime(msg.internal_date);

  var fromLine = '**发件人**\n' + fromName;
  if (fromMail) {
    fromLine += ' <' + fromMail + '>';
  }

  var elements = [
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
  var card = JSON.parse(JSON.stringify(CARD_TEMPLATE));
  card.header.subtitle.content = _truncate(subject, SUBJECT_TRUNCATE_LIMIT);
  card.body.elements = elements;
  return card;
}

/**
 * 构造带 Authorization 头的请求配置。
 * @param {string} method - HTTP 方法
 * @param {string} url - 完整 URL
 * @param {Object} [body] - 请求体
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
      `feishu-im: API 失败 code=${body.code} msg=${body.msg || ''}; url=${url}`
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
  if (err.message && err.message.indexOf('feishu-im:') !== -1) {
    return err;
  }
  if (err.response) {
    var status = err.response.status;
    var respBody = err.response.data;
    return new Error(
      `feishu-im: HTTP ${status} body=${JSON.stringify(respBody)}; url=${url}`
    );
  }
  return new Error(`feishu-im: ${err.message}; url=${url}`);
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
    if (err.response && err.response.status === 401) {
      try {
        await oauth.refreshTokensIfNeeded(true);
      } catch (refreshErr) {
        throw new Error(
          `feishu-im: token 刷新失败（401 重试）${refreshErr.message}; url=${url}`
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
 * 发送交互卡片到指定群聊。
 * @param {string} chatId - 目标群聊 chat_id（oc_ 开头）
 * @param {Object} cardContent - Card 2.0 交互卡片 JSON 对象
 * @returns {Promise<Object>} 发送结果（含 message_id 等）
 * @throws {Error} 含 status + body 的 Error
 */
async function sendCard(chatId, cardContent) {
  if (!chatId || typeof chatId !== 'string') {
    throw new Error(`feishu-im.sendCard: chatId 参数无效 (chatId=${chatId})`);
  }
  if (!cardContent || typeof cardContent !== 'object') {
    throw new Error(`feishu-im.sendCard: cardContent 参数无效 (chatId=${chatId})`);
  }
  var url = `${FEISHU_IM_API_BASE}/im/v1/messages?receive_id_type=chat_id`;
  var body = {
    receive_id: chatId,
    msg_type: 'interactive',
    content: JSON.stringify(cardContent),
  };
  return _request('POST', url, body);
}

module.exports = {
  sendCard: sendCard,
  buildMailCard: buildMailCard,
};
