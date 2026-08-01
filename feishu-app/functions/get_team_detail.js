'use strict';

/**
 * WorkBuddy 专家团工作区 · 团队详情查询云函数（team_workspace.html 前端调用）。
 *
 * 按团队维度聚合：团队信息 + 成员（AgentProfile）+ Mission 列表（含 WorkItem）
 * + 收到的跨团队协作请求。
 *
 * 入口签名：exports.main = async (event, context) => {...}
 * 入参（从 event.queryString 或 event 顶层读，兼容 GET/POST）：
 *   - team_key  团队唯一标识（必填）
 *   - status    Mission 状态过滤：'active'（进行中，排除终态）/ 'all'（全部，默认）
 *
 * 返回结构：
 *   {
 *     ok: true,
 *     team: { team_key, name, mission, active, lead_role_key, lead_role_name, ... },
 *     members: [ { team_key, role_key, name, is_lead, status, responsibilities, ... } ],
 *     missions: [ { ...mission, work_items: [ ... ] } ],
 *     collaborations: [ { from_team_key, to_team_key, objective, expected_artifact, status, ... } ]
 *   }
 * 异常返回：{ ok: false, error: string }
 */

const db = require('../lib/db.js');
const logger = require('../lib/logger.js');

/**
 * Mission 终态状态集合（进行中过滤时排除）。
 * 同时兼容 constants.MISSION_STATUS 与 base_schema.MISSION_STATUS_OPTIONS 中的终态。
 */
var TERMINAL_MISSION_STATUSES = ['COMPLETED', 'CANCELLED', 'FAILED'];

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
 * 妙搭云函数入口：查询团队工作区详情。
 * @param {Object} [event] - 触发器事件
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: boolean, team?, members?, missions?, collaborations?, error? }
 */
exports.main = async function (event, context) {
  try {
    var teamKey = _getParam(event, 'team_key');
    if (!teamKey) {
      return { ok: false, error: '缺少参数 team_key' };
    }
    var statusFilter = _getParam(event, 'status') || 'all';

    // 1. 查询团队信息
    var team = await db.queryOne(
      'SELECT * FROM teams WHERE team_key = ? LIMIT 1',
      [teamKey]
    );
    if (!team) {
      return { ok: false, error: '团队不存在: ' + teamKey };
    }

    // 2. 查询团队成员（主理人排在最前）
    var members = await db.query(
      'SELECT * FROM agents WHERE team_key = ? ORDER BY is_lead DESC, role_key ASC',
      [teamKey]
    );

    // 3. 查询该团队的 Mission 列表（可选状态过滤）
    var missionSql = 'SELECT * FROM missions WHERE team_key = ?';
    var missionParams = [teamKey];
    if (String(statusFilter).toLowerCase() === 'active') {
      var placeholders = TERMINAL_MISSION_STATUSES.map(function () { return '?'; }).join(', ');
      missionSql += ' AND status NOT IN (' + placeholders + ')';
      for (var i = 0; i < TERMINAL_MISSION_STATUSES.length; i++) {
        missionParams.push(TERMINAL_MISSION_STATUSES[i]);
      }
    }
    missionSql += ' ORDER BY created_at DESC, id DESC';
    var missions = await db.query(missionSql, missionParams);

    // 4. 对每个 Mission 查询关联的 WorkItem 列表
    var missionsWithItems = [];
    for (var m = 0; m < missions.length; m++) {
      var mission = missions[m];
      var missionId = mission.id != null ? mission.id : mission.mission_id;
      var workItems = [];
      if (missionId != null) {
        workItems = await db.query(
          'SELECT * FROM work_items WHERE mission_id = ? ORDER BY sequence ASC, id ASC',
          [missionId]
        );
      }
      var enriched = Object.assign({}, mission, { work_items: workItems });
      missionsWithItems.push(enriched);
    }

    // 5. 查询收到的协作请求
    var collaborations = await db.query(
      'SELECT * FROM collaborations WHERE to_team_key = ? ORDER BY created_at DESC, id DESC',
      [teamKey]
    );

    return {
      ok: true,
      team: team,
      members: Array.isArray(members) ? members : [],
      missions: missionsWithItems,
      collaborations: Array.isArray(collaborations) ? collaborations : [],
    };
  } catch (err) {
    logger.error(
      'get_team_detail: 查询团队详情异常 err=' +
        (err && err.message ? err.message : err)
    );
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
