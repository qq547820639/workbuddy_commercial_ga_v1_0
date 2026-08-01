'use strict';

/**
 * WorkBuddy 智能体执行 AgentRun 云函数。
 *
 * 核心闭环：Mission(ROUTED) → 主理人规划 WorkItem → AgentRun 调 LLM 执行 → 产出 Artifact + Evidence。
 * 本函数负责"AgentRun 执行"环节的编排：
 *   1. 参数：event.work_item_id 或 event.run_id
 *   2. 若传入 work_item_id：查询 WorkItem（状态必须为 ASSIGNED），创建 AgentRun（状态=RUNNING）
 *   3. 若传入 run_id：直接使用已有 AgentRun
 *   4. 调用 executor.executeRun
 *   5. 异常处理：AgentRun → FAILED，WorkItem → BLOCKED，写日志
 *   6. 返回 { ok: true, artifact: {...}, evidence: [...] } 或 { ok: false, error: ... }
 *
 * 入口签名：exports.main = async (event, context) => {...}
 * 入参：event.work_item_id 或 event.run_id（二选一，work_item_id 优先）
 */

const db = require('../lib/db');
const logger = require('../lib/logger');
const executor = require('../lib/executor');

/** AgentRun 状态枚举（从 executor 模块读取，已做防御性合并） */
const AGENT_RUN_STATUS = executor.AGENT_RUN_STATUS;
/** WorkItem 状态枚举 */
const WORK_ITEM_STATUS = executor.WORK_ITEM_STATUS;

/**
 * 返回当前时间的 'YYYY-MM-DD HH:MM:SS' 格式字符串。
 * @returns {string} 格式化时间
 */
function _nowString() {
  var d = new Date();
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
}

/**
 * 妙搭云函数入口：执行 AgentRun。
 * @param {Object} event - 触发器事件，需含 event.work_item_id 或 event.run_id
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: boolean, artifact?: {...}, evidence?: [...], error?: string }
 */
exports.main = async function (event, context) {
  var workItemId = event && event.work_item_id;
  var runId = event && event.run_id;

  if (!workItemId && !runId) {
    logger.error('execute_agent_run: event.work_item_id 和 event.run_id 均缺失');
    return { ok: false, error: 'event.work_item_id 或 event.run_id 至少需传一个' };
  }

  logger.info(
    `execute_agent_run: 开始执行 workItemId=${workItemId || 'N/A'} runId=${runId || 'N/A'}`
  );

  var workItem = null;
  var agentRunId = null;

  try {
    // 1. 若传入 work_item_id：查询 WorkItem + 创建 AgentRun
    if (workItemId) {
      var wiRows = await db.query(
        'SELECT * FROM work_items WHERE id = ? LIMIT 1',
        [workItemId]
      );
      workItem = wiRows && wiRows.length > 0 ? wiRows[0] : null;
      if (!workItem) {
        throw new Error(`WorkItem 不存在 workItemId=${workItemId}`);
      }
      if (workItem.status !== WORK_ITEM_STATUS.ASSIGNED) {
        throw new Error(
          `WorkItem 状态非 ASSIGNED（当前=${workItem.status}）workItemId=${workItemId}`
        );
      }

      // 创建 AgentRun（状态=RUNNING）
      var runInsert = await db.insert('agent_runs', {
        mission_id: workItem.mission_id,
        work_item_id: workItemId,
        agent_profile_id: workItem.assigned_agent_profile_id,
        skill_release_id: workItem.skill_release_id,
        status: AGENT_RUN_STATUS.RUNNING,
        started_at: _nowString(),
      });
      agentRunId = (runInsert && (runInsert.insertId || runInsert.id)) || null;
      if (!agentRunId) {
        throw new Error(`创建 AgentRun 失败，未返回 ID workItemId=${workItemId}`);
      }

      // WorkItem 状态 → RUNNING
      await db.update('work_items', workItemId, {
        status: WORK_ITEM_STATUS.RUNNING,
      });
    } else {
      // 2. 若传入 run_id：直接使用已有 AgentRun
      var runRows = await db.query(
        'SELECT * FROM agent_runs WHERE id = ? LIMIT 1',
        [runId]
      );
      var existingRun = runRows && runRows.length > 0 ? runRows[0] : null;
      if (!existingRun) {
        throw new Error(`AgentRun 不存在 runId=${runId}`);
      }
      agentRunId = runId;
      workItem = existingRun.work_item_id
        ? (await db.query('SELECT * FROM work_items WHERE id = ? LIMIT 1', [
            existingRun.work_item_id,
          ]))[0]
        : null;
    }

    // 3. 调用 executor.executeRun 执行
    var result = await executor.executeRun(agentRunId);

    logger.info(
      `execute_agent_run: 执行成功 runId=${agentRunId} artifactId=${result.artifact && result.artifact.id}`
    );

    // 4. 返回结果
    return {
      ok: true,
      artifact: result.artifact,
      evidence: result.evidence,
      agent_run: result.agent_run,
    };
  } catch (err) {
    // 5. 异常处理：AgentRun → FAILED，WorkItem → BLOCKED，写日志
    logger.error(
      `execute_agent_run: 执行异常 runId=${agentRunId || 'N/A'} cause=${err && err.message ? err.message : err}`
    );

    // AgentRun 状态 → FAILED（已创建 run 时）
    if (agentRunId) {
      try {
        await db.update('agent_runs', agentRunId, {
          status: AGENT_RUN_STATUS.FAILED,
          finished_at: _nowString(),
          close_reason: `failed:${err && err.message ? err.message.slice(0, 200) : 'unknown'}`,
        });
      } catch (updateErr) {
        logger.error(
          `execute_agent_run: AgentRun 状态更新失败 runId=${agentRunId} cause=${updateErr.message}`
        );
      }
    }

    // WorkItem 状态 → BLOCKED（已知 workItem 时）
    if (workItem && workItem.id) {
      try {
        await db.update('work_items', workItem.id, {
          status: WORK_ITEM_STATUS.BLOCKED,
        });
      } catch (updateErr) {
        logger.error(
          `execute_agent_run: WorkItem 状态更新失败 workItemId=${workItem.id} cause=${updateErr.message}`
        );
      }
    }

    // 6. 返回失败结果
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
      agent_run_id: agentRunId,
    };
  }
};
