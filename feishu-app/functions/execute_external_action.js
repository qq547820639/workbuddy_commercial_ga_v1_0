'use strict';

/**
 * WorkBuddy 执行外部操作云函数。
 *
 * 在审批通过后（或独立调用）执行对外动作（发邮件 / 发 IM / 创建任务），
 * 并记录 ExternalOperation 审计日志。
 *
 * 步骤：
 *   1. 校验 event.mission_id / event.action_type / event.action_data
 *   2. 调用 external_actions.executeExternalAction 执行操作
 *   3. 调用 external_actions.recordExternalOperation 记录审计日志
 *   4. 返回 { ok: true, result } 或 { ok: false, error }
 *
 * 入口签名：exports.main = async (event, context) => {...}
 * event: { mission_id, action_type, action_data }
 *   - action_type: send_email / send_im / create_task
 *   - action_data: 操作输入（结构见 external_actions.executeExternalAction）
 */

const externalActions = require('../lib/external_actions.js');
const logger = require('../lib/logger.js');

/**
 * 妙搭云函数入口：执行外部操作。
 * @param {Object} event - 触发参数 { mission_id, action_type, action_data }
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: true, result } 或 { ok: false, error }
 */
exports.main = async function (event, context) {
  try {
    const missionId = event && event.mission_id;
    const actionType = event && event.action_type;
    const actionData = event && event.action_data;

    // 1. 参数校验
    if (!missionId) {
      return { ok: false, error: '缺少 mission_id' };
    }
    if (!actionType) {
      return { ok: false, error: '缺少 action_type' };
    }
    const data = actionData && typeof actionData === 'object' ? actionData : {};

    // 2. 执行外部操作
    let result;
    try {
      result = await externalActions.executeExternalAction(
        missionId,
        actionType,
        data
      );
    } catch (err) {
      // 执行失败：记录审计日志后返回错误
      const failed = {
        ok: false,
        error: err && err.message ? err.message : String(err),
      };
      await externalActions.recordExternalOperation(
        missionId,
        actionType,
        data,
        failed
      );
      logger.error(
        `execute_external_action: 执行失败 mission=${missionId} ` +
        `action=${actionType} err=${err && err.message ? err.message : err}`
      );
      return { ok: false, error: failed.error };
    }

    // 3. 记录 ExternalOperation 审计日志
    await externalActions.recordExternalOperation(
      missionId,
      actionType,
      data,
      { ok: true, result: result }
    );

    logger.info(
      `execute_external_action: 执行成功 mission=${missionId} action=${actionType}`
    );

    // 4. 返回执行结果
    return { ok: true, result: result };
  } catch (err) {
    logger.error(
      `execute_external_action: 异常 err=${err && err.message ? err.message : err}`
    );
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
