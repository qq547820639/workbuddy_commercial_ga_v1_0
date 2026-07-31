'use strict';

/**
 * WorkBuddy 重发通知云函数（HTML 控制台前端 POST 调用）。
 *
 * 按 message_id 查归档记录，重发 IM 卡片到 NOTIFY_CHAT_ID 群聊。
 *
 * 入口签名说明：妙搭云函数入口约定为 exports.main = async (event, context) => {...}，
 * 具体 event / context 形态需在妙搭环境验证；POST body 从 event.body 读，
 * 可能是字符串需 JSON.parse，也可能是对象。
 *
 * 入参（从 event.body 读 JSON）：
 *   { message_id: string }
 *
 * 执行流程：
 *   1. 校验 message_id 非空
 *   2. 读 config 拿 NOTIFY_CHAT_ID
 *   3. SELECT * FROM mail_archive WHERE message_id = ? 拿归档记录
 *   4. 把归档记录转换回邮件对象结构（给 buildMailCard 用）
 *   5. 调 feishu-im.sendCard(chatId, feishu-im.buildMailCard(msg)) 发卡片
 *   6. logger.info 记录重发
 *   7. 返回 { ok: true, data: { message_id, subject } }
 *
 * 异常返回：{ ok: false, error: string }
 */

const db = require('../lib/db.js');
const config = require('../lib/config.js');
const feishuIm = require('../lib/feishu-im.js');
const logger = require('../lib/logger.js');

/**
 * 从 event.body 解析 JSON 入参，兼容字符串和对象两种形态。
 * @param {Object} event - 妙搭事件对象
 * @returns {{message_id: string}}
 * @throws {Error} body 缺失或非对象/JSON 时抛出
 */
function _parseBody(event) {
  let body = event && event.body;
  if (body == null) {
    throw new Error('resend_notification: event.body 缺失');
  }
  if (typeof body === 'string') {
    if (body.trim() === '') {
      throw new Error('resend_notification: event.body 为空字符串');
    }
    try {
      body = JSON.parse(body);
    } catch (e) {
      throw new Error(`resend_notification: event.body JSON 解析失败：${e.message}`);
    }
  }
  if (typeof body !== 'object' || Array.isArray(body)) {
    throw new Error('resend_notification: event.body 不是 JSON 对象');
  }
  return body;
}

/**
 * 把 received_at 时间字符串（'YYYY-MM-DD HH:MM:SS'）转回毫秒级 epoch。
 * Date.parse 按本地时区解析，与 feishu-im.js 的 _fmtTime（本地时区格式化）对称。
 * @param {string} receivedAt - 'YYYY-MM-DD HH:MM:SS' 格式时间字符串
 * @returns {string} 毫秒级 epoch 字符串；解析失败返回原值
 */
function _receivedAtToMs(receivedAt) {
  if (!receivedAt) {
    return '';
  }
  // 把 'YYYY-MM-DD HH:MM:SS' 转为 'YYYY-MM-DDTHH:MM:SS' 让 Date.parse 稳定解析
  const isoLike = String(receivedAt).replace(' ', 'T');
  const ms = Date.parse(isoLike);
  if (isNaN(ms)) {
    return String(receivedAt);
  }
  return String(ms);
}

/**
 * 把归档记录转换回邮件 message 对象结构（供 feishu-im.buildMailCard 使用）。
 * 字段映射对照 feishu-im.js buildMailCard 的读取字段：
 *   - message_id
 *   - subject
 *   - head_from: { name, mail_address }
 *   - internal_date（毫秒级 epoch 字符串）
 *   - body_preview
 *   - label_ids（数组）
 * @param {Object} row - mail_archive 行
 * @returns {Object} 邮件 message 对象
 */
function _buildMsgFromArchive(row) {
  const labelsStr =
    row.labels != null ? String(row.labels) : '';
  const labelIds = labelsStr
    .split(',')
    .map(function (s) { return s.trim(); })
    .filter(function (s) { return s.length > 0; });

  return {
    message_id: row.message_id || '',
    subject: row.subject || '',
    head_from: {
      name: row.from_name || '',
      mail_address: row.from_mail || '',
    },
    internal_date: _receivedAtToMs(row.received_at),
    body_preview: row.body_preview != null ? String(row.body_preview) : '',
    label_ids: labelIds,
  };
}

/**
 * 妙搭云函数入口：按 message_id 重发通知。
 * @param {Object} [event] - 触发器事件
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: boolean, data?: {...}, error?: string }
 */
exports.main = async function (event, context) {
  try {
    // 1. 解析 body
    const body = _parseBody(event);

    // 2. 校验 message_id 非空
    const messageId =
      body.message_id != null ? String(body.message_id).trim() : '';
    if (!messageId) {
      throw new Error('resend_notification: message_id 不能为空');
    }

    // 3. 读 config 拿 NOTIFY_CHAT_ID
    const chatId = await config.get('NOTIFY_CHAT_ID');
    if (!chatId) {
      throw new Error('resend_notification: 未配置 NOTIFY_CHAT_ID');
    }

    // 4. 查归档记录
    const row = await db.queryOne(
      'SELECT * FROM mail_archive WHERE message_id = ?',
      [messageId]
    );
    if (!row) {
      throw new Error(
        `resend_notification: 归档记录不存在 (message_id=${messageId})`
      );
    }

    // 5. 把归档记录转换回邮件对象结构
    const msg = _buildMsgFromArchive(row);

    // 6. 调 sendCard 发卡片
    const card = feishuIm.buildMailCard(msg);
    await feishuIm.sendCard(chatId, card);

    // 7. 记录重发日志
    const subjectBrief = String(msg.subject || '').slice(0, 40);
    logger.info(
      `resend_notification: 已重发通知 message_id=${messageId} subject=${subjectBrief}`
    );

    return {
      ok: true,
      data: {
        message_id: messageId,
        subject: msg.subject,
      },
    };
  } catch (err) {
    logger.error(
      `resend_notification: 重发通知异常 err=${err && err.message ? err.message : err}`
    );
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
