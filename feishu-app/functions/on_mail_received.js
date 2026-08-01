'use strict';

/**
 * WorkBuddy 邮件接收云函数（事件订阅入口）。
 *
 * 触发链路：飞书邮箱收到新邮件 → 事件订阅触发妙搭云函数 → 本函数处理。
 *
 * 处理流程：
 *   1. 解析邮件元数据（message_id/subject/from/body_preview/received_at）
 *   2. 去重：查 mail_archive 是否已存在该 message_id
 *   3. 写入 mail_archive 表（processing_status = NEW）
 *   4. 调 dispatch.proposeDispatch + dispatch.createMission 创建任务
 *   5. 高风险邮件（risk_level=high/critical）自动创建飞书审批（调 feishu-approval，实际审批在 Task 7 实现）
 *   6. supporting_team_keys 非空时创建 CollaborationRequest
 *   7. 发 IM 通知给主理人
 *
 * 异常处理：吞掉异常写日志，不抛出（事件订阅要求 200 响应）。
 *
 * 仅依赖 Node.js 内置模块 + 共享库，不依赖任何第三方库。
 */

const db = require('../lib/db');
const logger = require('../lib/logger');
const dispatch = require('../lib/dispatch');

/**
 * 从事件订阅回调中解析邮件元数据。
 * 兼容多种事件载荷形态（data/message/obj/裸字段）。
 * @param {Object} event - 飞书事件订阅回调事件
 * @returns {Object} 邮件元数据 { message_id, subject, from_name, from_mail, body_preview, received_at }
 */
function _extractMail(event) {
  const obj = event || {};
  const data = obj.data || obj.event || obj.obj || obj;
  const msg = (data && (data.message || data.mail)) || data || {};
  const headFrom = (msg && msg.head_from) || {};
  return {
    message_id: msg.message_id || msg.id || obj.message_id || '',
    subject: msg.subject || obj.subject || '(无主题)',
    from_name: headFrom.name || msg.from_name || obj.from_name || '',
    from_mail: headFrom.mail_address || msg.from_mail || obj.from_mail || '',
    body_preview: msg.body_preview || msg.body_text || obj.body_preview || '',
    received_at:
      msg.internal_date || msg.received_at || obj.received_at || Date.now(),
  };
}

/**
 * 将 received_at（毫秒级 epoch 或时间字符串）归一化为 'YYYY-MM-DD HH:MM:SS'。
 * 与 feishu-im._fmtTime / dispatch._now 一致（本地时区）。
 * @param {string|number} receivedAt - 接收时间
 * @returns {string} 格式化时间字符串
 */
function _fmtReceivedAt(receivedAt) {
  const ms = parseInt(receivedAt, 10);
  if (!isNaN(ms) && ms > 0) {
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
  }
  // 非数字epoch：若已是字符串直接返回，否则用当前时间
  if (typeof receivedAt === 'string' && receivedAt) {
    return receivedAt;
  }
  const d = new Date();
  const pad = (n) => (n < 10 ? '0' + n : '' + n);
  return (
    d.getFullYear() + '-' +
    pad(d.getMonth() + 1) + '-' +
    pad(d.getDate()) + ' ' +
    pad(d.getHours()) + ':' +
    pad(d.getMinutes()) + ':' +
    pad(d.getSeconds())
  );
}

/**
 * 邮件接收云函数入口。
 * @param {Object} event - 飞书事件订阅回调事件
 * @param {Object} [context] - 云函数上下文
 * @returns {Promise<Object>} 处理结果 { ok, ... }；异常时也返回 { ok:false, error }，不抛出
 */
exports.main = async function (event, context) {
  let mail;
  try {
    mail = _extractMail(event);
  } catch (err) {
    logger.error(`on_mail_received: 解析邮件元数据失败 ${err.message}`);
    return { ok: false, error: 'parse_failed' };
  }

  const messageId = mail.message_id;
  if (!messageId) {
    logger.warn('on_mail_received: 缺少 message_id，跳过处理');
    return { ok: false, error: 'missing_message_id' };
  }

  try {
    // 1. 去重：查 mail_archive 是否已存在该 message_id
    let existed = null;
    try {
      existed = await db.queryOne(
        'SELECT id FROM mail_archive WHERE message_id = ? LIMIT 1',
        [messageId]
      );
    } catch (err) {
      logger.warn(`on_mail_received: 去重查询失败 ${err.message}`);
    }
    if (existed) {
      logger.info(`on_mail_received: 邮件已处理过，跳过 message_id=${messageId}`);
      return { ok: true, deduplicated: true, message_id: messageId };
    }

    // 2. 写入 mail_archive 表
    const archiveFields = {
      message_id: messageId,
      subject: mail.subject,
      from_name: mail.from_name,
      from_mail: mail.from_mail,
      received_at: _fmtReceivedAt(mail.received_at),
      body_preview: mail.body_preview,
      labels: '',
      processing_status: 'NEW',
    };
    try {
      await db.insert('mail_archive', archiveFields);
      logger.info(`on_mail_received: 已归档邮件 message_id=${messageId} subject=${mail.subject}`);
    } catch (err) {
      logger.error(`on_mail_received: 写入 mail_archive 失败 ${err.message}`);
      // 归档失败不阻断后续派单，继续处理
    }

    // 3. dispatch 派单 + 创建 Mission
    const dispatchResult = await dispatch.proposeDispatch(mail);
    logger.info(
      `on_mail_received: 派单结果 primary=${dispatchResult.primary_team_key} risk=${dispatchResult.risk_level} confidence=${dispatchResult.confidence}`
    );

    const mission = await dispatch.createMission(dispatchResult, mail);

    // 4. 高风险邮件自动创建飞书审批（实际审批在 Task 7 实现）
    const riskLevel = dispatchResult.risk_level;
    if (riskLevel === 'high' || riskLevel === 'critical') {
      try {
        // 飞书审批实际创建在 Task 7 实现，此处先占位 require
        const approval = require('../lib/feishu-approval.js');
        if (approval && typeof approval.createApproval === 'function') {
          await approval.createApproval({
            mission_id: mission && mission.id,
            risk_level: riskLevel,
            subject: mail.subject,
            mail_data: mail,
          });
          logger.info(
            `on_mail_received: 已创建飞书审批（高风险邮件）missionId=${mission && mission.id}`
          );
        } else {
          logger.warn(
            'on_mail_received: feishu-approval 模块未提供 createApproval（待 Task 7 实现）'
          );
        }
      } catch (err) {
        logger.warn(
          `on_mail_received: 飞书审批创建跳过（待 Task 7）：${err.message}`
        );
      }
    }

    // 5. supporting_team_keys 非空时创建协作请求
    const supporting = dispatchResult.supporting_team_keys || [];
    if (supporting.length > 0 && mission && mission.id) {
      try {
        await dispatch.createCollaborationRequests(mission.id, supporting);
      } catch (err) {
        logger.warn(`on_mail_received: 创建协作请求失败 ${err.message}`);
      }
    }

    // 6. 发 IM 通知给主理人
    try {
      await dispatch.notifyLead(mission);
    } catch (err) {
      logger.warn(`on_mail_received: 通知主理人失败 ${err.message}`);
    }

    return {
      ok: true,
      message_id: messageId,
      mission_id: mission && mission.id,
      primary_team_key: dispatchResult.primary_team_key,
      risk_level: riskLevel,
    };
  } catch (err) {
    // 异常处理：吞掉异常写日志，不抛出（事件订阅要求 200 响应）
    logger.error(
      `on_mail_received: 处理邮件失败 message_id=${messageId} ${err.message}`
    );
    return { ok: false, error: err.message, message_id: messageId };
  }
};
