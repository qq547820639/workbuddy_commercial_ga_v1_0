'use strict';

/**
 * WorkBuddy 专家团看板数据云函数（HTML 控制台前端 GET 调用）。
 *
 * 返回全部 active 专家团的看板汇总：每支团队的主理人、进行中任务数、
 * 活跃工作项数、待审批数与最近活动时间，供 dashboard.html 渲染卡片网格。
 *
 * 统计口径（对照 .trae/specs/expert-team-workspace-delivery/spec.md
 *  "看板展示全部 active 团队" 场景）：
 *   - 进行中任务数：missions.status ∈ 进行中状态集合 且 team_key = 该团队
 *   - 活跃工作项数：work_items.status ∈ 活跃状态集合 且所属 mission 属于该团队
 *   - 待审批数：approvals.status = PENDING 且所属 mission 属于该团队
 *   - 最近活动时间：该团队最近一条 mission 的 created_at
 *
 * 实现说明：
 *   - missions / work_items / approvals 之间通过 missions.id 关联
 *     （work_items.mission_id、approvals.mission_id 均引用 missions.id，
 *      与 plan_workitems.js / on_approval_callback.js 一致）。
 *   - teams.active / agents.is_lead 为 checkbox 字段，存储形态可能是
 *     boolean / 0,1 / 'true','1' 等，统一在 JS 侧做 truthy 判断，避免 SQL
 *     方言差异。
 *   - 不使用 JOIN / GROUP BY（妙搭 SQL 引擎兼容性未知），改为按团队维度
 *     在 JS 侧聚合，查询次数固定为 5 次（团队 / 任务 / 智能体 / 工作项 / 审批），
 *     并对结果集做安全上限保护。
 *
 * 入口签名：exports.main = async (event, context) => {...}，本函数不依赖入参。
 *
 * 返回结构：
 *   {
 *     ok: true,
 *     teams: Array<{
 *       team_key: string,
 *       name: string,
 *       mission: string,
 *       lead_name: string,
 *       active_missions: number,
 *       active_work_items: number,
 *       pending_approvals: number,
 *       last_activity: string|null
 *     }>
 *   }
 * 异常返回：{ ok: false, error: string }
 */

const db = require('../lib/db.js');
const logger = require('../lib/logger.js');
const schema = require('../lib/base_schema.js');

// 表名取自 base_schema（含 tableKey），避免硬编码
const TEAMS_TABLE = schema.TEAMS_TABLE.tableKey; // 'teams'
const AGENTS_TABLE = schema.AGENTS_TABLE.tableKey; // 'agents'
const MISSIONS_TABLE = schema.MISSIONS_TABLE.tableKey; // 'missions'
const WORK_ITEMS_TABLE = schema.WORK_ITEMS_TABLE.tableKey; // 'work_items'
const APPROVALS_TABLE = schema.APPROVALS_TABLE.tableKey; // 'approvals'

/**
 * 进行中任务状态集合。
 * 对照 spec 与 base_schema.MISSION_STATUS_OPTIONS：排除终态
 * （COMPLETED / CANCELLED / FAILED / UNKNOWN）与早期接入态
 * （INGESTED / DISPATCH_REVIEW / NEEDS_INFORMATION / BLOCKED），
 * 保留从路由完成到验证阶段之间的全部"在途"状态。
 */
const IN_PROGRESS_MISSION_STATUSES = [
  'ROUTED',
  'LEAD_TRIAGE',
  'PLANNING',
  'READY',
  'EXECUTING',
  'LEAD_REVIEW',
  'APPROVAL_REQUIRED',
  'APPROVED',
  'ACTION_EXECUTING',
  'VERIFYING',
];

/** 活跃工作项状态集合（对照 spec 与 base_schema.WORK_ITEM_STATUS_OPTIONS）。 */
const ACTIVE_WORK_ITEM_STATUSES = ['ASSIGNED', 'RUNNING', 'SUBMITTED'];

/** 待审批状态（对照 base_schema.APPROVAL_STATUS_OPTIONS）。 */
const PENDING_APPROVAL_STATUS = 'PENDING';

/** 单次拉取的安全上限（看板数据量有限，防止极端情况下内存膨胀）。 */
const MISSION_FETCH_LIMIT = 5000;
const WORK_ITEM_FETCH_LIMIT = 10000;
const APPROVAL_FETCH_LIMIT = 10000;

// 预构建状态集合，便于 O(1) 查表
const IN_PROGRESS_SET = {};
IN_PROGRESS_MISSION_STATUSES.forEach(function (s) {
  IN_PROGRESS_SET[s] = true;
});
const ACTIVE_WORK_ITEM_SET = {};
ACTIVE_WORK_ITEM_STATUSES.forEach(function (s) {
  ACTIVE_WORK_ITEM_SET[s] = true;
});

/**
 * checkbox 字段的 truthy 判断（兼容 boolean / 0,1 / 'true','1' 等存储形态）。
 * @param {*} v - 字段值
 * @returns {boolean}
 */
function _isTruthy(v) {
  return v === true || v === 1 || v === '1' || v === 'true';
}

/**
 * 构造 IN 占位符字符串，如 3 个值 → '?, ?, ?'。
 * @param {number} n - 值的数量
 * @returns {string} 占位符字符串；n<=0 返回空串
 */
function _placeholders(n) {
  if (n <= 0) return '';
  var arr = [];
  for (var i = 0; i < n; i++) arr.push('?');
  return arr.join(', ');
}

/**
 * 妙搭云函数入口：查询专家团看板汇总数据。
 * @param {Object} [event] - 触发器事件（本函数不使用）
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: boolean, teams?: [...], error?: string }
 */
exports.main = async function (event, context) {
  try {
    // 1. 拉取全部团队，在 JS 侧过滤 active（checkbox 存储形态兼容）
    const allTeams = await db.query(
      'SELECT team_key, name, mission, lead_role_name, active FROM ' +
        TEAMS_TABLE
    );
    const teamList = Array.isArray(allTeams) ? allTeams : [];
    const activeTeams = teamList.filter(function (t) {
      return t && t.team_key && _isTruthy(t.active);
    });

    // 无 active 团队直接返回空列表
    if (activeTeams.length === 0) {
      return { ok: true, teams: [] };
    }

    const teamKeys = activeTeams.map(function (t) {
      return t.team_key;
    });
    const teamKeySet = {};
    teamKeys.forEach(function (k) {
      teamKeySet[k] = true;
    });

    // 2. 并行拉取：该批团队的 missions（含 id/team_key/status/created_at）
    //    与 agents（用于解析主理人姓名）
    const missionsPromise = db.query(
      'SELECT id, team_key, status, created_at FROM ' +
        MISSIONS_TABLE +
        ' WHERE team_key IN (' +
        _placeholders(teamKeys.length) +
        ') ORDER BY created_at DESC LIMIT ?',
      teamKeys.concat([MISSION_FETCH_LIMIT])
    );
    const agentsPromise = db.query(
      'SELECT team_key, name, is_lead FROM ' +
        AGENTS_TABLE +
        ' WHERE team_key IN (' +
        _placeholders(teamKeys.length) +
        ')',
      teamKeys
    );
    const [missionsRaw, agentsRaw] = await Promise.all([
      missionsPromise,
      agentsPromise,
    ]);
    const missions = Array.isArray(missionsRaw) ? missionsRaw : [];
    const agents = Array.isArray(agentsRaw) ? agentsRaw : [];

    // 3. 任务维度聚合：mission_id → team_key 映射、进行中任务计数、最近活动时间
    //    missions 已按 created_at DESC 排序，故每个团队首次出现即为其最近一条
    const missionTeamMap = {}; // mission_id(String) -> team_key
    const activeMissionsByTeam = {}; // team_key -> 进行中任务数
    const lastActivityByTeam = {}; // team_key -> created_at
    teamKeys.forEach(function (k) {
      activeMissionsByTeam[k] = 0;
    });

    missions.forEach(function (m) {
      const tk = m.team_key;
      if (!tk || !teamKeySet[tk]) return;
      const mid = String(m.id);
      missionTeamMap[mid] = tk;
      if (m.status && IN_PROGRESS_SET[m.status]) {
        activeMissionsByTeam[tk] = (activeMissionsByTeam[tk] || 0) + 1;
      }
      if (lastActivityByTeam[tk] === undefined && m.created_at != null) {
        lastActivityByTeam[tk] = m.created_at;
      }
    });

    // 4. 主理人姓名：取每支团队第一个 is_lead=true 的 agent，回退到 teams.lead_role_name
    const leadNameByTeam = {};
    agents.forEach(function (a) {
      const tk = a.team_key;
      if (!tk || !teamKeySet[tk]) return;
      if (_isTruthy(a.is_lead) && leadNameByTeam[tk] === undefined) {
        leadNameByTeam[tk] = a.name || '';
      }
    });

    // 5. 工作项 / 审批维度聚合：通过 mission_id 反查 team_key 后在 JS 侧计数
    const workItemsByTeam = {}; // team_key -> 活跃工作项数
    const approvalsByTeam = {}; // team_key -> 待审批数
    teamKeys.forEach(function (k) {
      workItemsByTeam[k] = 0;
      approvalsByTeam[k] = 0;
    });

    const missionIds = Object.keys(missionTeamMap);
    if (missionIds.length > 0) {
      const wiPromise = db.query(
        'SELECT mission_id, status FROM ' +
          WORK_ITEMS_TABLE +
          ' WHERE mission_id IN (' +
          _placeholders(missionIds.length) +
          ') LIMIT ?',
        missionIds.concat([WORK_ITEM_FETCH_LIMIT])
      );
      const apPromise = db.query(
        'SELECT mission_id, status FROM ' +
          APPROVALS_TABLE +
          ' WHERE mission_id IN (' +
          _placeholders(missionIds.length) +
          ') LIMIT ?',
        missionIds.concat([APPROVAL_FETCH_LIMIT])
      );
      const [workItemsRaw, approvalsRaw] = await Promise.all([
        wiPromise,
        apPromise,
      ]);
      const workItems = Array.isArray(workItemsRaw) ? workItemsRaw : [];
      const approvals = Array.isArray(approvalsRaw) ? approvalsRaw : [];

      workItems.forEach(function (wi) {
        const tk = missionTeamMap[String(wi.mission_id)];
        if (!tk) return;
        if (wi.status && ACTIVE_WORK_ITEM_SET[wi.status]) {
          workItemsByTeam[tk] = (workItemsByTeam[tk] || 0) + 1;
        }
      });
      approvals.forEach(function (ap) {
        const tk = missionTeamMap[String(ap.mission_id)];
        if (!tk) return;
        if (ap.status === PENDING_APPROVAL_STATUS) {
          approvalsByTeam[tk] = (approvalsByTeam[tk] || 0) + 1;
        }
      });
    }

    // 6. 组装返回结果（保持 activeTeams 原始顺序）
    const teams = activeTeams.map(function (t) {
      const tk = t.team_key;
      return {
        team_key: tk,
        name: t.name || '',
        mission: t.mission || '',
        lead_name: leadNameByTeam[tk] || t.lead_role_name || '',
        active_missions: activeMissionsByTeam[tk] || 0,
        active_work_items: workItemsByTeam[tk] || 0,
        pending_approvals: approvalsByTeam[tk] || 0,
        last_activity: lastActivityByTeam[tk] || null,
      };
    });

    return { ok: true, teams: teams };
  } catch (err) {
    logger.error(
      'get_dashboard: 查询看板数据异常 err=' +
        (err && err.message ? err.message : err)
    );
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
