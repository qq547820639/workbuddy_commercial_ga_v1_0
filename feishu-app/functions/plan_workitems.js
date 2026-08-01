'use strict';

/**
 * WorkBuddy 规划工作项云函数。
 *
 * 核心闭环：Mission(ROUTED) → 主理人规划 WorkItem → AgentRun 调 LLM 执行。
 * 本函数负责"主理人规划 WorkItem"环节的编排：
 *   1. 查询 Mission（状态必须为 ROUTED）
 *   2. Mission 状态 → PLANNING
 *   3. 调用 planner.buildPlan 生成 WorkItem 列表
 *   4. 每个 WorkItem 写入 db（work_items 表）+ 创建飞书子任务
 *   5. Mission 状态 → READY（规划完成）
 *   6. 返回 { ok: true, work_items: [...] }
 *   7. 异常处理：写日志，Mission 状态回退 ROUTED
 *
 * 入口签名：exports.main = async (event, context) => {...}
 * 入参：event.mission_id
 */

const db = require('../lib/db');
const logger = require('../lib/logger');
const oauth = require('../lib/feishu-oauth');
const planner = require('../lib/planner');
const feishuTask = require('../lib/feishu-task');

/** Mission 状态枚举（从 planner 模块读取，已做防御性合并） */
const MISSION_STATUS = planner.MISSION_STATUS;
/** WorkItem 状态枚举 */
const WORK_ITEM_STATUS = planner.WORK_ITEM_STATUS;

/**
 * 妙搭云函数入口：规划工作项。
 * @param {Object} event - 触发器事件，需含 event.mission_id
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: boolean, work_items?: [...], error?: string }
 */
exports.main = async function (event, context) {
  var missionId = event && event.mission_id;
  if (!missionId) {
    logger.error('plan_workitems: event.mission_id 缺失');
    return { ok: false, error: 'event.mission_id 缺失' };
  }

  logger.info(`plan_workitems: 开始规划 missionId=${missionId}`);

  try {
    // 1. 查询 Mission（状态必须为 ROUTED）
    var missionRows = await db.query(
      'SELECT * FROM missions WHERE id = ? LIMIT 1',
      [missionId]
    );
    var mission = missionRows && missionRows.length > 0 ? missionRows[0] : null;
    if (!mission) {
      throw new Error(`Mission 不存在 missionId=${missionId}`);
    }
    if (mission.status !== MISSION_STATUS.ROUTED) {
      throw new Error(
        `Mission 状态非 ROUTED（当前=${mission.status}）missionId=${missionId}`
      );
    }

    // 2. Mission 状态 → PLANNING
    await db.update('missions', mission.id, {
      status: MISSION_STATUS.PLANNING,
    });

    // 3. 调用 planner.buildPlan 生成 WorkItem 列表
    var planResult = await planner.buildPlan(mission);
    var workItems = planResult.work_items || [];

    // 4. 每个 WorkItem 写入 db（work_items 表）+ 创建飞书子任务
    var createdItems = [];
    var userToken = null;
    var parentTaskId = mission.feishu_task_id || null;

    // 尝试获取 user_access_token（用于创建飞书子任务，失败不阻断）
    try {
      userToken = await oauth.getUserAccessToken();
    } catch (err) {
      logger.warn(
        `plan_workitems: 获取 user_access_token 失败，跳过飞书子任务创建 cause=${err.message}`
      );
    }

    for (var i = 0; i < workItems.length; i++) {
      var wi = workItems[i];

      // 4a. 写入 work_items 表
      var insertResult = await db.insert('work_items', wi);
      var wiId = (insertResult && (insertResult.insertId || insertResult.id)) || null;

      // 4b. 创建飞书子任务（token 可用时）
      var feishuTaskId = null;
      if (userToken) {
        try {
          var taskResult = parentTaskId
            ? await feishuTask.createSubTask(
                userToken,
                parentTaskId,
                wi.title,
                wi.objective || ''
              )
            : await feishuTask.createTask(
                userToken,
                wi.title,
                wi.objective || ''
              );
          feishuTaskId =
            (taskResult && (taskResult.task_guid || taskResult.task_id)) || null;
        } catch (err) {
          // 单个子任务创建失败不阻断，仅记日志
          logger.warn(
            `plan_workitems: 创建飞书子任务失败 item_key=${wi.item_key} cause=${err.message}`
          );
        }
      }

      createdItems.push({
        id: wiId,
        item_key: wi.item_key,
        title: wi.title,
        status: wi.status,
        assigned_agent_name: wi.assigned_agent_name,
        assigned_role: wi.assigned_role,
        skill_name: wi.skill_name,
        sequence: wi.sequence,
        depends_on: wi.depends_on,
        feishu_task_id: feishuTaskId,
      });
    }

    // 5. Mission 状态 → READY（规划完成）
    await db.update('missions', mission.id, {
      status: MISSION_STATUS.READY,
    });

    logger.info(
      `plan_workitems: 规划完成 missionId=${missionId} workItemCount=${createdItems.length}`
    );

    // 6. 返回结果
    return {
      ok: true,
      work_items: createdItems,
      missing_information: planResult.missing_information || [],
    };
  } catch (err) {
    // 7. 异常处理：写日志，Mission 状态回退 ROUTED
    logger.error(
      `plan_workitems: 规划异常 missionId=${missionId} cause=${err && err.message ? err.message : err}`
    );
    // 尝试回退 Mission 状态为 ROUTED（失败静默，仅记日志）
    try {
      await db.update('missions', missionId, {
        status: MISSION_STATUS.ROUTED,
      });
    } catch (rollbackErr) {
      logger.error(
        `plan_workitems: Mission 状态回退失败 missionId=${missionId} cause=${rollbackErr.message}`
      );
    }
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
