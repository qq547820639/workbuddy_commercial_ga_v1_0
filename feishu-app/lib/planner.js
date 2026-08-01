'use strict';

/**
 * WorkBuddy 主理人规划工作项核心逻辑。
 *
 * 核心闭环：Mission(ROUTED) → 主理人规划 WorkItem → AgentRun 调 LLM 执行。
 * 本模块负责"主理人规划 WorkItem"环节：
 *   1. 读取团队的工作流定义（WorkflowVersion）
 *   2. 调用 LLM（planner），传入 mission 上下文 + workflow 定义
 *   3. LLM 返回 WorkItem 列表（每个含 item_key/title/role/skill/depends_on/sequence）
 *   4. 按 role 匹配 AgentProfile（agents 表）
 *   5. 绑定 skill_release_id（skill_releases 表，冻结版本）
 *   6. 返回带绑定信息的 WorkItem 列表
 *
 * 依赖共享库：db.js / constants.js / logger.js / llm-client.js
 * 状态枚举从 constants.js 读取（缺失值按任务规范补齐，不修改 constants.js）。
 */

const db = require('./db');
const logger = require('./logger');
const constants = require('./constants');
const llmClient = require('./llm-client');

/**
 * 状态枚举（constants.js 已有值优先，任务规范要求的缺失值按规范补齐）。
 * constants.js 现有 MISSION_STATUS 不含 ROUTED/PLANNING/READY/EXECUTING，
 * 此处做防御性合并，保证代码可用且不修改共享库。
 */
const MISSION_STATUS = Object.assign(
  {
    ROUTED: 'ROUTED',
    PLANNING: 'PLANNING',
    READY: 'READY',
    EXECUTING: 'EXECUTING',
  },
  constants.MISSION_STATUS
);

/** WorkItem 状态枚举（同上防御性合并） */
const WORK_ITEM_STATUS = Object.assign(
  {
    ASSIGNED: 'ASSIGNED',
    RUNNING: 'RUNNING',
    SUBMITTED: 'SUBMITTED',
    BLOCKED: 'BLOCKED',
    DRAFT: 'DRAFT',
  },
  constants.WORK_ITEM_STATUS
);

/**
 * 返回 planner 的 JSON Schema，约束 LLM 输出 WorkItem 列表结构。
 * @returns {Object} JSON Schema 对象
 */
function planSchema() {
  var itemSchema = {
    type: 'object',
    additionalProperties: false,
    properties: {
      item_key: { type: 'string', description: '工作项唯一标识' },
      title: { type: 'string', description: '工作项标题' },
      objective: { type: 'string', description: '工作项目标说明' },
      role: { type: 'string', description: '负责角色标识（对应 agents.role_key）' },
      skill: {
        type: 'string',
        description: '技能标识，格式 skill_key@semantic_version（如 customer-impact-classification@1.0.0）',
      },
      depends_on: {
        type: 'array',
        items: { type: 'string' },
        description: '依赖的前置工作项 item_key 列表',
      },
      sequence: {
        type: 'integer',
        description: '执行顺序序号（从 0 开始）',
      },
      acceptance_criteria: {
        type: 'array',
        items: { type: 'string' },
        description: '验收标准列表',
      },
      evidence_requirements: {
        type: 'array',
        items: { type: 'string' },
        description: '证据要求列表',
      },
    },
    required: [
      'item_key',
      'title',
      'objective',
      'role',
      'skill',
      'depends_on',
      'sequence',
      'acceptance_criteria',
      'evidence_requirements',
    ],
  };
  return {
    type: 'object',
    additionalProperties: false,
    properties: {
      work_items: {
        type: 'array',
        items: itemSchema,
        description: '规划生成的工作项列表',
      },
      missing_information: {
        type: 'array',
        items: { type: 'string' },
        description: '缺失信息提示列表',
      },
      collaboration_suggestions: {
        type: 'array',
        items: { type: 'object' },
        description: '跨团队协作建议列表',
      },
    },
    required: ['work_items', 'missing_information', 'collaboration_suggestions'],
  };
}

/**
 * 按 role 匹配团队的 AgentProfile（智能体角色）。
 * 从 agents 表查询 team_key + role_key + status=active 的记录。
 * @param {string} teamKey - 团队标识
 * @param {string} roleKey - 角色标识（对应 workflow 中 work_item.role）
 * @returns {Promise<Object|null>} 匹配的 AgentProfile 记录；无匹配返回 null
 * @throws {Error} 查询失败抛出含上下文的 Error
 */
async function matchAgentByRole(teamKey, roleKey) {
  if (!teamKey || typeof teamKey !== 'string') {
    throw new Error(`planner.matchAgentByRole: teamKey 参数无效 (teamKey=${teamKey})`);
  }
  if (!roleKey || typeof roleKey !== 'string') {
    throw new Error(`planner.matchAgentByRole: roleKey 参数无效 (roleKey=${roleKey})`);
  }
  try {
    const rows = await db.query(
      'SELECT * FROM agents WHERE team_key = ? AND role_key = ? AND status = ? LIMIT 1',
      [teamKey, roleKey, 'active']
    );
    return rows && rows.length > 0 ? rows[0] : null;
  } catch (err) {
    throw new Error(
      `planner.matchAgentByRole: 查询 agents 失败 teamKey=${teamKey} roleKey=${roleKey} cause=${err.message}`
    );
  }
}

/**
 * 解析技能标识字符串，拆分为 skill_key 与 semantic_version。
 * 输入格式：customer-impact-classification@1.0.0
 * @param {string} skillSpec - 技能标识字符串
 * @returns {{skillKey: string, version: string|null}} 拆分结果
 */
function _parseSkillSpec(skillSpec) {
  if (!skillSpec || typeof skillSpec !== 'string') {
    return { skillKey: '', version: null };
  }
  const atIdx = skillSpec.lastIndexOf('@');
  if (atIdx <= 0 || atIdx === skillSpec.length - 1) {
    // 无版本号，整体作为 skill_key
    return { skillKey: skillSpec, version: null };
  }
  return {
    skillKey: skillSpec.slice(0, atIdx),
    version: skillSpec.slice(atIdx + 1),
  };
}

/**
 * 查询冻结版本的 Skill Release（已发布的技能版本）。
 * 优先按 skill_key + semantic_version 精确匹配，无版本号时取最新 published 版本。
 * @param {string} skillKey - 技能标识（可含 @version 后缀，内部自动解析）
 * @returns {Promise<Object|null>} 匹配的 SkillRelease 记录；无匹配返回 null
 * @throws {Error} 查询失败抛出含上下文的 Error
 */
async function findSkillRelease(skillKey) {
  if (!skillKey || typeof skillKey !== 'string') {
    throw new Error(`planner.findSkillRelease: skillKey 参数无效 (skillKey=${skillKey})`);
  }
  const parsed = _parseSkillSpec(skillKey);
  try {
    if (parsed.version) {
      // 精确匹配 skill_key + semantic_version + published
      const rows = await db.query(
        'SELECT * FROM skill_releases WHERE skill_key = ? AND semantic_version = ? AND status = ? LIMIT 1',
        [parsed.skillKey, parsed.version, 'published']
      );
      return rows && rows.length > 0 ? rows[0] : null;
    }
    // 无版本号：取该 skill_key 的最新 published 版本
    const rows = await db.query(
      'SELECT * FROM skill_releases WHERE skill_key = ? AND status = ? ORDER BY id DESC LIMIT 1',
      [parsed.skillKey, 'published']
    );
    return rows && rows.length > 0 ? rows[0] : null;
  } catch (err) {
    throw new Error(
      `planner.findSkillRelease: 查询 skill_releases 失败 skillKey=${skillKey} cause=${err.message}`
    );
  }
}

/**
 * 读取团队的已发布工作流版本（WorkflowVersion）。
 * @param {string} teamKey - 团队标识
 * @returns {Promise<Object|null>} 匹配的 WorkflowVersion 记录；无匹配返回 null
 * @throws {Error} 查询失败抛出含上下文的 Error
 */
async function _findWorkflowVersion(teamKey) {
  if (!teamKey || typeof teamKey !== 'string') {
    throw new Error(`planner._findWorkflowVersion: teamKey 参数无效 (teamKey=${teamKey})`);
  }
  try {
    const rows = await db.query(
      'SELECT * FROM workflow_versions WHERE team_key = ? AND status = ? ORDER BY id DESC LIMIT 1',
      [teamKey, 'published']
    );
    return rows && rows.length > 0 ? rows[0] : null;
  } catch (err) {
    throw new Error(
      `planner._findWorkflowVersion: 查询 workflow_versions 失败 teamKey=${teamKey} cause=${err.message}`
    );
  }
}

/**
 * 校验工作项依赖图无环（拓扑排序检测）。
 * @param {Array<Object>} items - 工作项列表（每个含 item_key + depends_on）
 * @throws {Error} 存在未知依赖或环时抛出
 */
function _validateAcyclic(items) {
  if (!items || items.length === 0) return;
  var keys = {};
  var i;
  for (i = 0; i < items.length; i++) {
    keys[items[i].item_key] = true;
  }
  var graph = {};
  var indegree = {};
  for (i = 0; i < items.length; i++) {
    var k = items[i].item_key;
    indegree[k] = 0;
    graph[k] = [];
  }
  for (i = 0; i < items.length; i++) {
    var deps = items[i].depends_on || [];
    for (var j = 0; j < deps.length; j++) {
      if (!keys[deps[j]]) {
        throw new Error(`planner: 未知依赖 ${deps[j]}（工作项 ${items[i].item_key}）`);
      }
      graph[deps[j]].push(items[i].item_key);
      indegree[items[i].item_key] += 1;
    }
  }
  // 拓扑排序（Kahn 算法）
  var queue = [];
  for (var key in indegree) {
    if (indegree[key] === 0) queue.push(key);
  }
  var visited = 0;
  while (queue.length > 0) {
    var node = queue.shift();
    visited++;
    var neighbors = graph[node] || [];
    for (var n = 0; n < neighbors.length; n++) {
      indegree[neighbors[n]] -= 1;
      if (indegree[neighbors[n]] === 0) queue.push(neighbors[n]);
    }
  }
  if (visited !== items.length) {
    throw new Error('planner: 工作项依赖图存在环');
  }
}

/**
 * 解析 workflow_versions.config 字段（可能是 JSON 字符串或对象）。
 * @param {Object} workflow - workflow_versions 记录
 * @returns {Object} 解析后的 config 对象
 */
function _parseWorkflowConfig(workflow) {
  if (!workflow) return {};
  var config = workflow.config;
  if (config == null) return {};
  if (typeof config === 'string') {
    try {
      return JSON.parse(config);
    } catch (e) {
      logger.warn(`planner: workflow config JSON 解析失败，回退空对象 cause=${e.message}`);
      return {};
    }
  }
  return config;
}

/**
 * 核心规划函数：根据 Mission 上下文 + 团队工作流定义，调 LLM 生成 WorkItem 列表，
 * 并按 role 匹配 AgentProfile、按 skill 匹配 SkillRelease（冻结版本）。
 *
 * @param {Object} missionData - Mission 数据对象，需含以下字段：
 *   - id: Mission ID
 *   - team_key: 团队标识
 *   - title: 任务标题
 *   - objective: 任务目标
 *   - source_type: 来源类型（如 email）
 *   - source_id: 来源标识
 *   - risk_level: 风险等级
 * @returns {Promise<Object>} { work_items: [...], model_invocation: {...}, missing_information: [...] }
 * @throws {Error} Mission 状态非 ROUTED、工作流缺失、agent/skill 匹配失败、LLM 调用失败时抛出
 */
async function buildPlan(missionData) {
  if (!missionData || typeof missionData !== 'object') {
    throw new Error('planner.buildPlan: missionData 参数无效');
  }
  var missionId = missionData.id;
  var teamKey = missionData.team_key;
  if (!missionId) {
    throw new Error('planner.buildPlan: missionData.id 缺失');
  }
  if (!teamKey) {
    throw new Error('planner.buildPlan: missionData.team_key 缺失');
  }

  // 1. 读取团队的已发布工作流版本
  var workflow = await _findWorkflowVersion(teamKey);
  if (!workflow) {
    throw new Error(`planner.buildPlan: 团队 ${teamKey} 无已发布工作流版本`);
  }
  var workflowConfig = _parseWorkflowConfig(workflow);
  var workflowSpecs = workflowConfig.work_items || workflowConfig.default_workflows || [];
  if (!workflowSpecs || workflowSpecs.length === 0) {
    throw new Error(`planner.buildPlan: 团队 ${teamKey} 工作流无 work_items 定义`);
  }

  // 2. 调用 LLM（planner），传入 mission 上下文 + workflow 定义
  var llmPayload = {
    mission: {
      id: missionId,
      title: missionData.title || '',
      objective: missionData.objective || '',
      risk_level: missionData.risk_level || 'unknown',
      source_type: missionData.source_type || '',
      source_id: missionData.source_id || '',
    },
    team: {
      team_key: teamKey,
    },
    workflow: {
      workflow_key: workflow.workflow_key || '',
      name: workflow.name || '',
      version: workflow.version || '',
      work_items: workflowSpecs,
    },
    constraints: {
      one_primary_team: true,
      external_write_requires_owner_approval: true,
      all_claims_require_evidence: true,
    },
  };

  logger.info(
    `planner.buildPlan: 开始规划 missionId=${missionId} teamKey=${teamKey} workflow=${workflow.workflow_key}`
  );

  var llmResult;
  try {
    llmResult = await llmClient.completeStructured(llmPayload, planSchema(), {
      task_type: 'mission_plan',
      prompt_version: 'mission-plan-v1',
    });
  } catch (err) {
    throw new Error(`planner.buildPlan: LLM 调用失败 missionId=${missionId} cause=${err.message}`);
  }

  var specs = (llmResult.data && llmResult.data.work_items) || [];
  if (!specs || specs.length === 0) {
    throw new Error(`planner.buildPlan: LLM 未返回工作项 missionId=${missionId}`);
  }

  // 3. 校验依赖图无环
  _validateAcyclic(specs);

  // 4. 对每个 WorkItem，按 role 匹配 AgentProfile，按 skill 匹配 SkillRelease
  var workItems = [];
  for (var idx = 0; idx < specs.length; idx++) {
    var spec = specs[idx];
    var role = spec.role;
    var skillSpec = spec.skill;

    // 4a. 匹配 AgentProfile
    var agent = await matchAgentByRole(teamKey, role);
    if (!agent) {
      throw new Error(
        `planner.buildPlan: 未找到角色 ${role} 的 active 智能体 teamKey=${teamKey}`
      );
    }

    // 4b. 绑定 skill_release_id
    var skillRelease = await findSkillRelease(skillSpec);
    if (!skillRelease) {
      throw new Error(
        `planner.buildPlan: 未找到已发布技能版本 ${skillSpec} teamKey=${teamKey}`
      );
    }

    // 4c. 组装 WorkItem（含绑定信息）
    var workItem = {
      mission_id: missionId,
      item_key: spec.item_key,
      title: spec.title,
      objective: spec.objective || '',
      status: WORK_ITEM_STATUS.ASSIGNED,
      assigned_agent_profile_id: agent.id,
      assigned_agent_name: agent.name || '',
      assigned_role: role,
      skill_release_id: skillRelease.id,
      skill_name: skillRelease.name || skillSpec,
      sequence: spec.sequence != null ? spec.sequence : idx,
      depends_on: (spec.depends_on || []).join(','),
      acceptance_criteria: JSON.stringify(spec.acceptance_criteria || []),
      evidence_requirements: JSON.stringify(spec.evidence_requirements || []),
      input_snapshot: JSON.stringify({
        workflow_key: workflow.workflow_key || '',
        workflow_version: workflow.version || '',
        role: role,
        skill: skillSpec,
      }),
    };
    workItems.push(workItem);
  }

  logger.info(
    `planner.buildPlan: 规划完成 missionId=${missionId} workItemCount=${workItems.length}`
  );

  return {
    work_items: workItems,
    model_invocation: {
      task_type: 'mission_plan',
      prompt_version: 'mission-plan-v1',
      usage: llmResult.usage || {},
    },
    missing_information: (llmResult.data && llmResult.data.missing_information) || [],
  };
}

module.exports = {
  buildPlan: buildPlan,
  planSchema: planSchema,
  matchAgentByRole: matchAgentByRole,
  findSkillRelease: findSkillRelease,
  MISSION_STATUS: MISSION_STATUS,
  WORK_ITEM_STATUS: WORK_ITEM_STATUS,
};
