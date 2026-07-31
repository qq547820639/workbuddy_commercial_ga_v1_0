'use strict';

/**
 * WorkBuddy 邮件轮询云函数（妙搭自动触发，每 60s 调用一次，无需入参）。
 *
 * 替代 feishu/watch_worker.py 的 _poll_once，核心链路：
 *   1. 从 config 表读 NOTIFY_CHAT_ID（通知目标群聊）。
 *   2. 调 feishu-mail.listUnread() 拉未读邮件 message_id 列表。
 *   3. SQL 查 mail_archive 表过滤掉已归档（已通知）的 message_id。
 *   4. 若无新邮件 → 更新 worker_status.last_poll_at → 返回。
 *   5. 调 feishu-mail.getMessages(newIds) 批量拉邮件详情。
 *   6. 对每封邮件：
 *        a. feishu-im.sendCard(chatId, buildMailCard(msg)) 发 IM 卡片通知；
 *        b. INSERT INTO mail_archive (...)，processing_status = 'NOTIFIED'。
 *   7. 更新 worker_status：last_poll_at = NOW()，total_notified += N。
 *   8. 单封邮件处理失败 → logger.error + 继续下一封，不阻断。
 *   9. 整个函数异常 → logger.error + 不抛出（自动触发任务不容许失败影响下次）。
 *
 * 入口签名说明：妙搭云函数入口约定为 exports.main = async (event, context) => {...}，
 * 具体 event / context 形态需在妙搭环境验证；本函数不依赖入参。
 */

const feishuMail = require('../lib/feishu-mail.js');
const feishuIm = require('../lib/feishu-im.js');
const db = require('../lib/db.js');
const logger = require('../lib/logger.js');
const config = require('../lib/config.js');
const { PROCESSING_STATUS } = require('../lib/constants.js');

/** 邮件正文预览归档长度（与 watch_worker.py / constants.BODY_PREVIEW_LIMIT 一致） */
const BODY_PREVIEW_ARCHIVE_LIMIT = 300;

/**
 * internal_date（毫秒级 epoch）转 'YYYY-MM-DD HH:MM:SS'。
 * 与 feishu/watch_worker.py 的 _fmt_internal_date、feishu-im.js 的 _fmtTime 一致。
 * @param {string|number} internalDate - 毫秒级 epoch
 * @returns {string} 格式化时间字符串；无效时回退为原值的字符串形式（或空串）
 */
function _formatInternalDate(internalDate) {
  if (internalDate == null || internalDate === '') {
    return '';
  }
  try {
    const ms = parseInt(internalDate, 10);
    if (isNaN(ms)) {
      return String(internalDate);
    }
    const d = new Date(ms);
    const pad = function (n) {
      return n < 10 ? '0' + n : '' + n;
    };
    return (
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
      `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
    );
  } catch (e) {
    return String(internalDate);
  }
}

/**
 * 从邮件详情构造 mail_archive 归档记录字段。
 * 字段映射对照 feishu/watch_worker.py 的 _build_mail_archive_fields。
 * @param {Object} msg - 邮件 message 对象（feishu-mail.getMessages 返回元素）
 * @returns {Object} mail_archive 列名到值的映射，processing_status = 'NOTIFIED'
 */
function _buildArchiveFields(msg) {
  const headFrom = msg.head_from || {};
  const rawLabels = msg.label_ids || msg.labels || [];
  let labelsStr;
  if (Array.isArray(rawLabels)) {
    labelsStr = rawLabels
      .filter(function (l) { return l; })
      .map(function (l) { return String(l); })
      .join(',');
  } else {
    labelsStr = String(rawLabels);
  }
  const bodyPreview = String(
    msg.body_preview == null ? '' : msg.body_preview
  ).slice(0, BODY_PREVIEW_ARCHIVE_LIMIT);
  return {
    message_id: msg.message_id || '',
    subject: msg.subject || '',
    from_name: headFrom.name || '',
    from_mail: headFrom.mail_address || '',
    received_at: _formatInternalDate(msg.internal_date),
    body_preview: bodyPreview,
    labels: labelsStr,
    processing_status: PROCESSING_STATUS.NOTIFIED,
  };
}

/**
 * 更新 worker_status 单行表（id=1）。
 * @param {number} [notifiedCount] - 本轮成功通知数；不传则只更新 last_poll_at
 * @returns {Promise<void>}
 */
async function _touchWorkerStatus(notifiedCount) {
  if (notifiedCount === undefined) {
    await db.execute(
      'UPDATE worker_status SET last_poll_at = NOW() WHERE id = 1'
    );
  } else {
    await db.execute(
      'UPDATE worker_status SET last_poll_at = NOW(), total_notified = total_notified + ? WHERE id = 1',
      [notifiedCount]
    );
  }
}

/**
 * 妙搭云函数入口：单次邮件轮询。
 * @param {Object} [event] - 触发器事件（本函数不使用）
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: boolean, data?: {...}, error?: string }
 */
exports.main = async function (event, context) {
  try {
    // 1. 读通知目标群聊
    const chatId = await config.get('NOTIFY_CHAT_ID');
    if (!chatId) {
      logger.warn('poll_once: 未配置 NOTIFY_CHAT_ID，跳过本轮轮询');
      await _touchWorkerStatus();
      return { ok: true, data: { skipped: true, reason: 'NO_CHAT_ID', newCount: 0 } };
    }

    // 2. 拉未读邮件 message_id 列表
    const unreadIds = await feishuMail.listUnread();

    // 3. 过滤掉已归档（已通知）的 message_id
    let freshIds = unreadIds;
    if (unreadIds.length > 0) {
      const placeholders = unreadIds.map(function () { return '?'; }).join(', ');
      const rows = await db.queryAll(
        `SELECT message_id FROM mail_archive WHERE message_id IN (${placeholders})`,
        unreadIds
      );
      const archivedSet = new Set();
      for (let i = 0; i < rows.length; i++) {
        if (rows[i] && rows[i].message_id) {
          archivedSet.add(rows[i].message_id);
        }
      }
      freshIds = unreadIds.filter(function (id) {
        return !archivedSet.has(id);
      });
    }

    logger.info(
      `poll_once: 未读 ${unreadIds.length}，待通知 ${freshIds.length}`
    );

    // 4. 无新邮件 → 更新 last_poll_at → 返回
    if (freshIds.length === 0) {
      await _touchWorkerStatus();
      return { ok: true, data: { newCount: 0 } };
    }

    // 5. 批量拉邮件详情
    const messages = await feishuMail.getMessages(freshIds);

    // 6. 逐封发通知 + 归档；单封失败只记日志，继续下一封
    let notified = 0;
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      const mid = (msg && msg.message_id) || '?';
      const subjectBrief = String((msg && msg.subject) || '?').slice(0, 40);
      try {
        const card = feishuIm.buildMailCard(msg);
        await feishuIm.sendCard(chatId, card);
        await db.insert('mail_archive', _buildArchiveFields(msg));
        notified++;
        logger.info(`poll_once: 已通知 message_id=${mid} subject=${subjectBrief}`);
      } catch (err) {
        // 8. 单封邮件处理失败 → 记日志 + 继续下一封，不阻断
        logger.error(
          `poll_once: 处理邮件失败 message_id=${mid} subject=${subjectBrief} ` +
          `err=${err && err.message ? err.message : err}`
        );
      }
    }

    // 7. 更新 worker_status：last_poll_at = NOW()，total_notified += notified
    await _touchWorkerStatus(notified);

    logger.info(`poll_once: 本轮完成，成功通知 ${notified} 封`);
    return { ok: true, data: { newCount: freshIds.length, notified: notified } };
  } catch (err) {
    // 9. 兜底：任何异常都吞掉，仅记日志，不抛出（避免影响下次自动触发）
    logger.error(
      `poll_once: 轮询异常 err=${err && err.message ? err.message : err}`
    );
    return { ok: false, error: err && err.message ? err.message : String(err) };
  }
};
