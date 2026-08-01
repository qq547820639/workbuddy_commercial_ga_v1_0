'use strict';

/**
 * WorkBuddy 智能体执行 AgentRun 核心逻辑。
 *
 * 核心闭环：Mission(ROUTED) → 主理人规划 WorkItem → AgentRun 调 LLM 执行 → 产出 Artifact + Evidence。
 * 本模块负责"AgentRun 调 LLM 执行 → 产出 Artifact + Evidence"环节：
 *   1. 创建 AgentRun 记录（状态=RUNNING）
 *   2. 构建 LLM 输入上下文（payload）
 *   3. 调用 LLM（completeStructured，传入 payload + agentOutputSchema）
 *   4. LLM 返回 artifact + evidence
 *   5. 创建 Artifact 记录（含 content_hash）
 *   6. 创建 Evidence 记录（含验证状态）
 *   7. AgentRun 状态 → SUBMITTED，WorkItem 状态 → SUBMITTED
 *   8. 记录 ModelInvocation（token 用量）
 *   9. 返回执行结果
 *
 * 依赖共享库：db.js / constants.js / logger.js / llm-client.js
 * 状态枚举从 constants.js 读取（缺失值按任务规范补齐，不修改 constants.js）。
 */

const crypto = require('crypto');
const db = require('./db');
const logger = require('./logger');
const constants = require('./constants');
const llmClient = require('./llm-client');

/**
 * 状态枚举（constants.js 已有值优先，任务规范要求的缺失值按规范补齐）。
 * constants.js 现有 AGENT_RUN_STATUS 不含 SUBMITTED/CLOSED/CONTEXT_PREPARED/OUTPUT_SUBMITTED，
 * 此处做防御性合并，保证代码可用且不修改共享库。
 */
const AGENT_RUN_STATUS = Object.assign(
  {
    RUNNING: 'RUNNING',
    SUBMITTED: 'SUBMITTED',
    CLOSED: 'CLOSED',
    FAILED: 'FAILED',
    CONTEXT_PREPARED: 'CONTEXT_PREPARED',
    OUTPUT_SUBMITTED: 'OUTPUT_SUBMITTED',
  },
  constants.AGENT_RUN_STATUS
);

/** WorkItem 状态枚举（同上防御性合并） */
const WORK_ITEM_STATUS = Object.assign(
  {
    ASSIGNED: 'ASSIGNED',
    RUNNING: 'RUNNING',
    SUBMITTED: 'SUBMITTED',
    BLOCKED: 'BLOCKED',
  },
  constants.WORK_ITEM_STATUS
);

/**
 * 返回 agent 执行结果的 JSON Schema，约束 LLM 输出 artifact + evidence 结构。
 * @returns {Object} JSON Schema 对象
 */
function agentOutputSchema() {
  var evidenceItem = {
    type: 'object',
    additionalProperties: false,
    properties: {
      claim: { type: 'string', description: '证据支撑的论断' },
      source_type: { type: 'string', description: '来源类型（如 email/document/system）' },
      source_id: { type: 'string', description: '来源标识' },
      source_excerpt: {
        type: ['string', 'null'],
        description: '来源摘录（可为 null）',
      },
      verification_status: {
        type: 'string',
        enum: ['verified', 'unverified', 'disputed'],
        description: '验证状态',
      },
      confidence: {
        type: 'integer',
        minimum: 0,
        maximum: 100,
        description: '置信度（0-100）',
      },
    },
    required: [
      'claim',
      'source_type',
      'source_id',
      'source_excerpt',
      'verification_status',
      'confidence',
    ],
  };
  return {
    type: 'object',
    additionalProperties: false,
    properties: {
      artifact: {
        type: 'object',
        additionalProperties: false,
        properties: {
          type: { type: 'string', description: '产物类型（如 response/analysis/plan）' },
          title: { type: 'string', description: '产物标题' },
          summary: { type: 'string', description: '产物摘要' },
          facts: {
            type: 'array',
            items: { type: 'string' },
            description: '已确认的事实列表',
          },
          assumptions: {
            type: 'array',
            items: { type: 'string' },
            description: '假设列表',
          },
          recommendations: {
            type: 'array',
            items: { type: 'string' },
            description: '建议列表',
          },
          missing_information: {
            type: 'array',
            items: { type: 'string' },
            description: '缺失信息列表',
          },
          draft_email: {
            type: ['object', 'null'],
            description: '草稿邮件（可为 null）',
            properties: {
              subject: { type: 'string' },
              body: { type: 'string' },
            },
          },
        },
        required: [
          'type',
          'title',
          'summary',
          'facts',
          'assumptions',
          'recommendations',
          'missing_information',
          'draft_email',
        ],
      },
      evidence: {
        type: 'array',
        items: evidenceItem,
        description: '证据列表',
      },
    },
    required: ['artifact', 'evidence'],
  };
}

/**
 * 计算内容的 SHA-256 哈希值（用于 Artifact 的 content_hash）。
 * @param {string|Object} content - 内容（字符串或对象，对象会先 JSON 序列化）
 * @returns {string} 64 字符的十六进制 SHA-256 哈希
 */
function contentHash(content) {
  var str;
  if (content == null) {
    str = '';
  } else if (typeof content === 'string') {
    str = content;
  } else {
    str = JSON.stringify(content);
  }
  return crypto.createHash('sha256').update(str, 'utf8').digest('hex');
}

/**
 * 将可能为 JSON 字符串的字段解析为对象。
 * @param {*} value - 原始值
 * @returns {*} 解析后的对象或原值
 */
function _parseJsonField(value) {
  if (value == null) return value;
  if (typeof value === 'string') {
    try {
      return JSON.parse(value);
    } catch (e) {
      return value;
    }
  }
  return value;
}

/**
 * 构建发送给 LLM 的输入上下文（payload）。
 * @param {Object} mission - Mission 记录
 * @param {Object} workItem - WorkItem 记录
 * @param {Object} agentProfile - AgentProfile 记录
 * @param {Object} skill - 技能配置（含 name + release.config）
 * @param {Object} [source] - 来源邮件信息（Mission.source_type=email 时为 MailMessage 记录）
 * @returns {Object} LLM 输入上下文
 */
function buildAgentPayload(mission, workItem, agentProfile, skill, source) {
  return {
    mission: mission || {},
    work_item: workItem || {},
    agent_profile: agentProfile || {},
    skill: {
      name: (skill && skill.name) || 'Unknown Skill',
      release: (skill && skill.release) || {},
    },
    source: source || {},
    security_boundary: {
      untrusted_content: ['source.body_text', 'source.body_html'],
      external_write_allowed: false,
      data_scope: 'current_mission',
    },
  };
}

/**
 * 核心执行函数：执行一次 AgentRun。
 *
 * 流程：
 *   1. 查询 AgentRun 记录（状态须为 RUNNING）
 *   2. 查询关联的 Mission / WorkItem / AgentProfile / SkillRelease / 来源邮件
 *   3. 构建 payload
 *   4. 调用 LLM（completeStructured，传入 payload + agentOutputSchema）
 *   5. 创建 Artifact 记录（含 content_hash）
 *   6. 创建 Evidence 记录（含验证状态）
 *   7. AgentRun 状态 → SUBMITTED
 *   8. WorkItem 状态 → SUBMITTED
 *   9. 记录 ModelInvocation（token 用量）
 *   10. 返回执行结果
 *
 * @param {string|number} runId - AgentRun 记录 ID
 * @returns {Promise<Object>} { agent_run, artifact, evidence, model_invocation }
 * @throws {Error} AgentRun 不存在/状态非 RUNNING/LLM 调用失败/写入失败时抛出
 */
async function executeRun(runId) {
  if (runId == null) {
    throw new Error('executor.executeRun: runId 参数无效');
  }

  // 1. 查询 AgentRun 记录
  var runRows = await db.query('SELECT * FROM agent_runs WHERE id = ? LIMIT 1', [runId]);
  var run = runRows && runRows.length > 0 ? runRows[0] : null;
  if (!run) {
    throw new Error(`executor.executeRun: AgentRun 不存在 runId=${runId}`);
  }
  if (run.status !== AGENT_RUN_STATUS.RUNNING) {
    throw new Error(
      `executor.executeRun: AgentRun 状态非 RUNNING（当前=${run.status}）runId=${runId}`
    );
  }

  var missionId = run.mission_id;
  var workItemId = run.work_item_id;
  var agentProfileId = run.agent_profile_id;
  var skillReleaseId = run.skill_release_id;

  // 2. 查询关联实体
  var missionRows = await db.query('SELECT * FROM missions WHERE id = ? LIMIT 1', [missionId]);
  var mission = missionRows && missionRows.length > 0 ? missionRows[0] : null;

  var workItemRows = await db.query('SELECT * FROM work_items WHERE id = ? LIMIT 1', [workItemId]);
  var workItem = workItemRows && workItemRows.length > 0 ? workItemRows[0] : null;

  var agentRows = await db.query('SELECT * FROM agents WHERE id = ? LIMIT 1', [agentProfileId]);
  var agentProfile = agentRows && agentRows.length > 0 ? agentRows[0] : null;

  var skillRelease = null;
  var skill = null;
  if (skillReleaseId) {
    var releaseRows = await db.query('SELECT * FROM skill_releases WHERE id = ? LIMIT 1', [skillReleaseId]);
    skillRelease = releaseRows && releaseRows.length > 0 ? releaseRows[0] : null;
  }
  if (skillRelease) {
    skill = {
      name: skillRelease.name || 'Unknown Skill',
      release: _parseJsonField(skillRelease.config) || {},
    };
  } else {
    skill = { name: 'Unknown Skill', release: {} };
  }

  // 来源邮件信息
  var source = null;
  if (mission && mission.source_type === 'email' && mission.source_id) {
    var sourceRows = await db.query(
      'SELECT * FROM mail_archive WHERE message_id = ? LIMIT 1',
      [mission.source_id]
    );
    source = sourceRows && sourceRows.length > 0 ? sourceRows[0] : null;
  }

  // 3. 构建 payload
  var payload = buildAgentPayload(mission, workItem, agentProfile, skill, source);

  logger.info(
    `executor.executeRun: 开始执行 runId=${runId} missionId=${missionId} workItemId=${workItemId}`
  );

  // 4. 调用 LLM
  var llmResult;
  try {
    llmResult = await llmClient.completeStructured(payload, agentOutputSchema(), {
      task_type: 'agent_execute',
      prompt_version: 'agent-execute-v1',
    });
  } catch (err) {
    // LLM 调用失败：记录失败信息到 AgentRun.output，不在此处变更状态（由调用方处理 FAILED）
    logger.error(
      `executor.executeRun: LLM 调用失败 runId=${runId} cause=${err.message}`
    );
    throw new Error(`executor.executeRun: LLM 调用失败 runId=${runId} cause=${err.message}`);
  }

  var artifactData = (llmResult.data && llmResult.data.artifact) || {};
  var evidenceList = (llmResult.data && llmResult.data.evidence) || [];
  var usage = llmResult.usage || {};

  // 5. 创建 Artifact 记录（含 content_hash）
  var artifactContent = JSON.stringify(artifactData);
  var hash = contentHash(artifactContent);
  var artifactResult = await db.insert('artifacts', {
    mission_id: missionId,
    work_item_id: workItemId,
    agent_run_id: runId,
    artifact_type: artifactData.type || 'unknown',
    content_hash: hash,
    content: artifactContent,
  });
  var artifactId = (artifactResult && (artifactResult.insertId || artifactResult.id)) || null;

  // 6. 创建 Evidence 记录（含验证状态）
  var evidenceRecords = [];
  for (var i = 0; i < evidenceList.length; i++) {
    var ev = evidenceList[i];
    var evResult = await db.insert('evidence', {
      mission_id: missionId,
      artifact_id: artifactId,
      evidence_type: ev.source_type || 'unknown',
      source_id: ev.source_id || '',
      claim: ev.claim || '',
      source_excerpt: ev.source_excerpt || null,
      status: ev.verification_status || 'unverified',
      confidence: ev.confidence != null ? ev.confidence : 0,
    });
    evidenceRecords.push({
      id: (evResult && (evResult.insertId || evResult.id)) || null,
      claim: ev.claim || '',
      source_type: ev.source_type || 'unknown',
      verification_status: ev.verification_status || 'unverified',
      confidence: ev.confidence != null ? ev.confidence : 0,
    });
  }

  // 7. AgentRun 状态 → SUBMITTED
  await db.update('agent_runs', runId, {
    status: AGENT_RUN_STATUS.SUBMITTED,
    finished_at: _nowString(),
  });

  // 8. WorkItem 状态 → SUBMITTED
  if (workItemId) {
    await db.update('work_items', workItemId, {
      status: WORK_ITEM_STATUS.SUBMITTED,
    });
  }

  // 9. 记录 ModelInvocation（token 用量）
  var invocationResult = null;
  try {
    invocationResult = await db.insert('model_invocations', {
      agent_run_id: runId,
      mission_id: missionId,
      task_type: 'agent_execute',
      prompt_version: 'agent-execute-v1',
      model_name: process.env.LLM_MODEL || process.env.OPENAI_MODEL || 'gpt-4o',
      prompt_tokens: usage.prompt_tokens || 0,
      completion_tokens: usage.completion_tokens || 0,
      total_tokens: usage.total_tokens || 0,
    });
    // 回填 AgentRun.model_invocation_id
    var invocationId = (invocationResult && (invocationResult.insertId || invocationResult.id)) || null;
    if (invocationId) {
      await db.update('agent_runs', runId, { model_invocation_id: invocationId });
    }
  } catch (err) {
    // ModelInvocation 记录失败不阻断主流程，仅记日志
    logger.warn(
      `executor.executeRun: 记录 ModelInvocation 失败 runId=${runId} cause=${err.message}`
    );
  }

  logger.info(
    `executor.executeRun: 执行完成 runId=${runId} artifactId=${artifactId} evidenceCount=${evidenceRecords.length}`
  );

  // 10. 返回执行结果
  return {
    agent_run: {
      id: runId,
      status: AGENT_RUN_STATUS.SUBMITTED,
      mission_id: missionId,
      work_item_id: workItemId,
    },
    artifact: {
      id: artifactId,
      artifact_type: artifactData.type || 'unknown',
      title: artifactData.title || '',
      summary: artifactData.summary || '',
      content_hash: hash,
    },
    evidence: evidenceRecords,
    model_invocation: {
      task_type: 'agent_execute',
      prompt_version: 'agent-execute-v1',
      usage: usage,
    },
  };
}

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

module.exports = {
  agentOutputSchema: agentOutputSchema,
  buildAgentPayload: buildAgentPayload,
  executeRun: executeRun,
  contentHash: contentHash,
  AGENT_RUN_STATUS: AGENT_RUN_STATUS,
  WORK_ITEM_STATUS: WORK_ITEM_STATUS,
};
