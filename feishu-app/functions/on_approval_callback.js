'use strict';

/**
 * WorkBuddy 飞书审批回调云函数。
 *
 * 接收飞书审批实例状态变更回调，驱动 Mission 状态机推进，闭环审批交付流程：
 *   - 审批通过：
 *       1. Mission 状态 → APPROVED
 *       2. 执行外部操作（调 external_actions.executeExternalAction）
 *       3. Mission 状态 → ACTION_EXECUTING → VERIFYING
 *       4. 发 IM 通知（操作已执行）
 *   - 审批拒绝：
 *       1. Mission 状态 → BLOCKED
 *       2. 发 IM 通知主理人（审批被拒绝）
 *
 * 异常处理：任何异常只写日志，不抛出（回调必须返回 200，否则飞书会重试）。
 *
 * 入口签名：exports.main = async (event, context) => {...}
 * event 形态（飞书审批回调，可能为 { event: {...} } 或裸事件对象）：
 *   { instance_id, status: 'APPROVED'|'REJECTED'|..., form: '<表单 JSON>' }
 */

const db = require('../lib/db.js');
const logger = require('../lib/logger.js');
const config = require('../lib/config.js');
const oauth = require('../lib/feishu-oauth.js');
const { MISSION_STATUS } = require('../lib/constants.js');
const externalActions = require('../lib/external_actions.js');

/**
 * Mission 状态扩展。
 * constants.MISSION_STATUS 仅含基础状态，审批闭环需要的状态（与
 * base_schema.js MISSION_STATUS_OPTIONS 一致）在此补充。
 */
const EXT_MISSION_STATUS = Object.assign({}, MISSION_STATUS, {
  APPROVAL_REQUIRED: 'APPROVAL_REQUIRED',
  APPROVED: 'APPROVED',
  ACTION_EXECUTING: 'ACTION_EXECUTING',
  VERIFYING: 'VERIFYING',
  BLOCKED: 'BLOCKED',
});

/** 飞书审批终态 */
const APPROVAL_STATUS_APPROVED = 'APPROVED';
const APPROVAL_STATUS_REJECTED = 'REJECTED';

/**
 * 更新 Mission 状态。失败只记日志，不抛异常。
 * @param {string} missionId - 任务 ID
 * @param {string} newStatus - 新状态
 * @returns {Promise<void>}
 */
async function _updateMissionStatus(missionId, newStatus) {
  try {
    await db.execute(
      'UPDATE missions SET status = ? WHERE id = ?',
      [newStatus, missionId]
    );
    logger.info(
      `on_approval_callback: Mission ${missionId} 状态 → ${newStatus}`
    );
  } catch (err) {
    logger.error(
      `on_approval_callback: 更新 Mission 状态失败 ${missionId} → ${newStatus} ` +
      `err=${err && err.message ? err.message : err}`
    );
  }
}

/**
 * 更新 approvals 表审批记录状态。失败只记日志，不抛异常。
 * @param {string} instanceId - 审批实例 ID
 * @param {string} status - 审批状态（APPROVED / REJECTED）
 * @returns {Promise<void>}
 */
async function _updateApprovalRecord(instanceId, status) {
  try {
    await db.execute(
      'UPDATE approvals SET status = ?, decided_at = NOW() WHERE approval_instance_id = ?',
      [status, instanceId]
    );
  } catch (err) {
    logger.error(
      `on_approval_callback: 更新审批记录失败 instance=${instanceId} ` +
      `err=${err && err.message ? err.message : err}`
    );
  }
}

/**
 * 发送 IM 通知到配置的通知群。失败只记日志，不抛异常。
 * @param {string} message - 通知文本
 * @returns {Promise<void>}
 */
async function _notifyChat(message) {
  try {
    const chatId = await config.get('NOTIFY_CHAT_ID');
    if (!chatId) {
      logger.warn('on_approval_callback: 未配置 NOTIFY_CHAT_ID，跳过 IM 通知');
      return;
    }
    const token = await oauth.getUserAccessToken();
    await externalActions.sendIM(token, chatId, message);
  } catch (err) {
    logger.error(
      `on_approval_callback: 发送 IM 通知失败 err=${err && err.message ? err.message : err}`
    );
  }
}

/**
 * 查询审批实例关联的 Mission ID。
 * 优先通过 approvals 表的 approval_instance_id 反查；回退到表单数据中的任务ID。
 * @param {string} instanceId - 审批实例 ID
 * @param {Object} formData - 审批表单数据
 * @returns {Promise<string|null>} Mission ID；未找到返回 null
 */
async function _resolveMissionId(instanceId, formData) {
  // 1. 通过审批实例 ID 反查 approvals 表
  if (instanceId) {
    try {
      const row = await db.queryOne(
        'SELECT mission_id FROM approvals WHERE approval_instance_id = ? LIMIT 1',
        [instanceId]
      );
      if (row && row.mission_id) {
        return row.mission_id;
      }
    } catch (err) {
      logger.warn(
        `on_approval_callback: 反查 approvals 表失败 instance=${instanceId} ` +
        `err=${err && err.message ? err.message : err}`
      );
    }
  }
  // 2. 回退：从表单数据取任务ID
  if (formData) {
    return formData['任务ID'] || formData.mission_id || formData.missionId || null;
  }
  return null;
}

/**
 * 妙搭云函数入口：处理飞书审批回调。
 * @param {Object} [event] - 回调事件（可能为 { event: {...} } 信封或裸事件对象）
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} 固定返回 { code: 0, msg: 'ok' }（HTTP 200 语义）
 */
exports.main = async function (event, context) {
  try {
    // 兼容 { event: {...} } 信封与裸事件对象
    const evt = (event && event.event) || event || {};
    const instanceId = evt.instance_id || evt.instanceId || '';
    const status = String(
      evt.status || evt.approve_status || ''
    ).toUpperCase();
    const formRaw = evt.form || evt.form_data || evt.formData || '';

    // 解析表单 JSON
    let formData = {};
    try {
      formData =
        typeof formRaw === 'string' ? JSON.parse(formRaw) : (formRaw || {});
    } catch (e) {
      formData = {};
    }

    logger.info(
      `on_approval_callback: 收到审批回调 instance_id=${instanceId} status=${status}`
    );

    if (!instanceId) {
      logger.warn('on_approval_callback: 回调缺少 instance_id，忽略');
      return { code: 0, msg: 'ok' };
    }

    // 查询关联 Mission
    const missionId = await _resolveMissionId(instanceId, formData);
    if (!missionId) {
      logger.warn(
        `on_approval_callback: 未找到审批实例 ${instanceId} 关联的 Mission，忽略`
      );
      return { code: 0, msg: 'ok' };
    }

    // 查询 Mission 详情（用于通知文案）
    let mission = null;
    try {
      mission = await db.queryOne(
        'SELECT * FROM missions WHERE id = ? LIMIT 1',
        [missionId]
      );
    } catch (err) {
      logger.warn(
        `on_approval_callback: 查询 Mission 失败 mission=${missionId} ` +
        `err=${err && err.message ? err.message : err}`
      );
    }
    const missionTitle = (mission && mission.title) || missionId;

    // 按审批状态分发处理
    if (status === APPROVAL_STATUS_APPROVED) {
      // —— 审批通过：执行外部操作并推进状态机 ——
      // 1. Mission 状态 → APPROVED
      await _updateMissionStatus(missionId, EXT_MISSION_STATUS.APPROVED);
      await _updateApprovalRecord(instanceId, APPROVAL_STATUS_APPROVED);

      // 2. Mission 状态 → ACTION_EXECUTING
      await _updateMissionStatus(missionId, EXT_MISSION_STATUS.ACTION_EXECUTING);

      // 3. 执行外部操作（默认发 IM 通知操作已执行）
      let actionResult = { ok: false, error: '未执行' };
      try {
        const raw = await externalActions.executeExternalAction(
          missionId,
          externalActions.ACTION_TYPES.SEND_IM,
          {
            chat_id: await config.get('NOTIFY_CHAT_ID'),
            message: `任务「${missionTitle}」审批已通过，外部操作开始执行。`,
          }
        );
        actionResult = { ok: true, result: raw };
      } catch (err) {
        actionResult = { ok: false, error: err && err.message ? err.message : String(err) };
        logger.error(
          `on_approval_callback: 执行外部操作失败 mission=${missionId} ` +
          `err=${err && err.message ? err.message : err}`
        );
      }
      // 记录外部操作审计日志（best-effort）
      await externalActions.recordExternalOperation(
        missionId,
        externalActions.ACTION_TYPES.SEND_IM,
        { mission_id: missionId, instance_id: instanceId },
        actionResult
      );

      // 4. Mission 状态 → VERIFYING
      await _updateMissionStatus(missionId, EXT_MISSION_STATUS.VERIFYING);

      // 5. 发 IM 通知（操作已执行）
      await _notifyChat(
        `任务「${missionTitle}」审批已通过，外部操作已执行，进入验证阶段。`
      );
    } else if (status === APPROVAL_STATUS_REJECTED) {
      // —— 审批拒绝：阻塞任务并通知主理人 ——
      // 1. Mission 状态 → BLOCKED
      await _updateMissionStatus(missionId, EXT_MISSION_STATUS.BLOCKED);
      await _updateApprovalRecord(instanceId, APPROVAL_STATUS_REJECTED);

      // 2. 发 IM 通知主理人（审批被拒绝）
      await _notifyChat(
        `任务「${missionTitle}」审批被拒绝，任务已阻塞，请主理人跟进处理。`
      );
    } else {
      // 非终态（PENDING / CANCELED 等），仅记日志
      logger.info(
        `on_approval_callback: 审批状态 ${status} 非终态，无需处理 mission=${missionId}`
      );
    }

    return { code: 0, msg: 'ok' };
  } catch (err) {
    // 兜底：任何异常都吞掉，仅记日志，不抛出（回调必须返回 200）
    logger.error(
      `on_approval_callback: 处理异常 err=${err && err.message ? err.message : err}`
    );
    return { code: 0, msg: 'ok' };
  }
};
