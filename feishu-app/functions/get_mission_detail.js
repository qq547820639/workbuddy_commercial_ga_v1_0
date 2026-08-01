'use strict';

/**
 * WorkBuddy 专家团工作区 · 任务详情查询云函数（team_workspace.html 前端调用）。
 *
 * 按 Mission 维度聚合：Mission + WorkItem 列表（每个 WorkItem 含 AgentRun 列表）
 * + Artifact 列表 + Evidence 列表。供工作区"任务"标签页展开 Mission 时懒加载。
 *
 * 入口签名：exports.main = async (event, context) => {...}
 * 入参（从 event.queryString 或 event 顶层读，兼容 GET/POST）：
 *   - mission_id  Mission 主键 id（必填）
 *
 * 返回结构：
 *   {
 *     ok: true,
 *     mission: { ... },
 *     work_items: [ { ...item, agent_runs: [ ... ] } ],
 *     artifacts: [ ... ],
 *     evidence: [ ... ]
 *   }
 * 异常返回：{ ok: false, error: string }
 */

const db = require('../lib/db.js');
const logger = require('../lib/logger.js');

/**
 * 从 event 中读取参数，兼容 event.queryString 与 event 顶层两种形态。
 * @param {Object} event - 妙搭事件对象
 * @param {string} key - 参数名
 * @returns {*} 参数值（可能为 undefined）
 */
function _getParam(event, key) {
  var src = (event && event.queryString) || event || {};
  return src[key];
}

/**
 * 妙搭云函数入口：查询任务详情（含 WorkItem/AgentRun/Artifact/Evidence）。
 * @param {Object} [event] - 触发器事件
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: boolean, mission?, work_items?, artifacts?, evidence?, error? }
 */
exports.main = async function (event, context) {
  try {
    var missionId = _getParam(event, 'mission_id');
    if (missionId === undefined || missionId === null || missionId === '') {
      return { ok: false, error: '缺少参数 mission_id' };
    }

    // 1. 查询 Mission
    var mission = await db.queryOne(
      'SELECT * FROM missions WHERE id = ? LIMIT 1',
      [missionId]
    );
    if (!mission) {
      return { ok: false, error: '任务不存在: ' + missionId };
    }

    // 2. 查询关联的 WorkItem 列表
    var workItems = await db.query(
      'SELECT * FROM work_items WHERE mission_id = ? ORDER BY sequence ASC, id ASC',
      [missionId]
    );

    // 3. 对每个 WorkItem 查询关联的 AgentRun 列表
    var itemsWithRuns = [];
    for (var i = 0; i < workItems.length; i++) {
      var item = workItems[i];
      var itemId = item.id != null ? item.id : item.item_id;
      var runs = [];
      if (itemId != null) {
        runs = await db.query(
          'SELECT * FROM agent_runs WHERE work_item_id = ? ORDER BY started_at DESC, id DESC',
          [itemId]
        );
      }
      itemsWithRuns.push(Object.assign({}, item, { agent_runs: runs }));
    }

    // 4. 查询关联的 Artifact 和 Evidence
    var artifacts = await db.query(
      'SELECT * FROM artifacts WHERE mission_id = ? ORDER BY created_at DESC, id DESC',
      [missionId]
    );
    var evidence = await db.query(
      'SELECT * FROM evidence WHERE mission_id = ? ORDER BY observed_at DESC, id DESC',
      [missionId]
    );

    return {
      ok: true,
      mission: mission,
      work_items: itemsWithRuns,
      artifacts: Array.isArray(artifacts) ? artifacts : [],
      evidence: Array.isArray(evidence) ? evidence : [],
    };
  } catch (err) {
    logger.error(
      'get_mission_detail: 查询任务详情异常 err=' +
        (err && err.message ? err.message : err)
    );
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
