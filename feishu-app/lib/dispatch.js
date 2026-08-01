'use strict';

/**
 * WorkBuddy dispatch 派单核心逻辑。
 * 邮件到达后：评分筛选候选团队 → 调 LLM 分类 → 创建 Mission → 创建协作请求 → 通知主理人。
 *
 * 仅依赖 Node.js 内置模块 + 共享库（db/config/logger/feishu-oauth/feishu-im/llm-client/constants），
 * 不依赖任何第三方库。
 *
 * routing_rules 说明：
 *   多维表格 teams 表（base_schema.js）未包含 routing_rules/charter 列（且不能修改共享库），
 *   故此处内置从 config/teams/*.yaml 提取的默认路由规则（与 seed_data.js 同源），
 *   以 team.mission 字段作为 charter。如需覆盖，可在 teams 表新增 routing_rules 列（JSON 文本），
 *   _loadTeamRouting 会优先读取该列。
 */

const db = require('./db');
const config = require('./config');
const logger = require('./logger');
const oauth = require('./feishu-oauth');
const feishuIm = require('./feishu-im');
const llmClient = require('./llm-client');

/**
 * 默认路由规则（从 config/teams/*.yaml 提取，与 seed_data.js 同源）。
 * 每个团队含 positive_signals（正向信号词）与 negative_signals（负向信号词）。
 */
const DEFAULT_ROUTING_RULES = {
  customer_success: {
    positive_signals: [
      'support', 'complaint', 'outage', 'renewal', 'issue', 'escalation',
      '投诉', '故障', '客户问题', '续约', '升级',
    ],
    negative_signals: ['供应商报价', '招聘', '税务'],
  },
  finance_ops: {
    positive_signals: [
      '发票', '账款', '应收', '应付', '报销', '预算', '财务', '报表',
      '对账', '付款', '收款', '税务', '增值税',
    ],
    negative_signals: ['审计', '投资', '融资'],
  },
  hr_people: {
    positive_signals: [
      '招聘', '简历', '面试', '入职', '离职', '员工关系', '薪酬', '福利',
      'HR', '人事', '培训', '绩效', '考勤', '假期',
    ],
    negative_signals: ['法律诉讼', '合同纠纷'],
  },
  operations_delivery: {
    positive_signals: [
      'delay', 'delivery', 'launch', 'supplier', 'incident', 'blocker',
      '延期', '上线', '交付', '供应商', '阻塞',
    ],
    negative_signals: ['报价请求', '法律意见', '招聘面试'],
  },
  sales_growth: {
    positive_signals: [
      'proposal', 'partnership', 'quote', 'pricing', 'discount', 'renewal',
      '商务', '报价', '合作', '分成', '续约',
    ],
    negative_signals: ['员工投诉', '基础设施故障', '税务申报'],
  },
};

/** 候选团队最大数量（传给 LLM 的上下文上限） */
const MAX_CANDIDATE_TEAMS = 5;

/** 评分超过该阈值才视为候选团队 */
const MIN_CANDIDATE_SCORE = 1;

/**
 * 当前时间格式化为 'YYYY-MM-DD HH:MM:SS'（本地时区，与 feishu-im._fmtTime 一致）。
 * @returns {string} 格式化时间字符串
 */
function _now() {
  const d = new Date();
  const pad = (n) => (n < 10 ? '0' + n : '' + n);
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
 * 判断 teams 表 active 字段是否为真（兼容 true/1/"true"/"1"）。
 * @param {*} val - active 字段值
 * @returns {boolean}
 */
function _isActive(val) {
  return val === true || val === 1 || val === '1' || val === 'true' || val === 'True';
}

/**
 * 文本评分：统计 signals 中在 text 里出现的词数（大小写不敏感）。
 * @param {string} text - 待评分文本
 * @param {Array<string>} signals - 信号词数组
 * @returns {number} 命中信号词数量；text 或 signals 无效返回 0
 */
function score(text, signals) {
  if (!text || !Array.isArray(signals) || signals.length === 0) {
    return 0;
  }
  const lower = String(text).toLowerCase();
  let count = 0;
  for (let i = 0; i < signals.length; i++) {
    const s = signals[i];
    if (s === null || s === undefined || s === '') continue;
    if (lower.indexOf(String(s).toLowerCase()) !== -1) {
      count++;
    }
  }
  return count;
}

/**
 * 返回 dispatch 结构化输出的 JSON Schema（OpenAI Responses API json_schema strict 兼容）。
 * 字段：business_type / primary_team_key / workflow_key / supporting_team_keys /
 *      risk_level / confidence / reasons / missing_information
 * @returns {Object} JSON Schema 对象
 */
function dispatchSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    properties: {
      business_type: { type: 'string', description: '业务类型' },
      primary_team_key: { type: 'string', description: '主理团队标识（必须来自候选团队）' },
      workflow_key: {
        type: ['string', 'null'],
        description: '工作流标识，无匹配时为 null',
      },
      supporting_team_keys: {
        type: 'array',
        items: { type: 'string' },
        description: '协作团队标识数组',
      },
      risk_level: {
        type: 'string',
        enum: ['low', 'medium', 'high', 'critical'],
        description: '风险等级',
      },
      confidence: {
        type: 'integer',
        minimum: 0,
        maximum: 100,
        description: '置信度 0-100',
      },
      reasons: {
        type: 'array',
        items: { type: 'string' },
        description: '派单理由',
      },
      missing_information: {
        type: 'array',
        items: { type: 'string' },
        description: '缺失信息',
      },
    },
    required: [
      'business_type',
      'primary_team_key',
      'workflow_key',
      'supporting_team_keys',
      'risk_level',
      'confidence',
      'reasons',
      'missing_information',
    ],
  };
}

/**
 * 从 db 读取所有 active 团队，并附加 routing_rules 与 charter。
 * @returns {Promise<Array<Object>>} 团队数组，每项含 team_key/name/mission/lead_role_key/lead_role_name/routing_rules/charter
 */
async function _loadActiveTeams() {
  let rows = [];
  try {
    rows = await db.query(
      'SELECT team_key, name, mission, lead_role_key, lead_role_name, active FROM teams',
      []
    );
  } catch (err) {
    logger.error(`dispatch._loadActiveTeams: 读取 teams 表失败 ${err.message}`);
    return [];
  }
  const teams = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i] || {};
    if (!_isActive(row.active)) continue;
    if (!row.team_key) continue;
    teams.push({
      team_key: row.team_key,
      name: row.name || row.team_key,
      mission: row.mission || '',
      lead_role_key: row.lead_role_key || '',
      lead_role_name: row.lead_role_name || '',
      routing_rules: DEFAULT_ROUTING_RULES[row.team_key] || {
        positive_signals: [],
        negative_signals: [],
      },
      charter: row.mission || '',
    });
  }
  return teams;
}

/**
 * 从邮件数据提取待评分文本（主题 + 发件人 + 正文预览）。
 * @param {Object} mailData - 邮件数据
 * @returns {string} 拼接后的文本
 */
function _mailText(mailData) {
  const data = mailData || {};
  const headFrom = data.head_from || {};
  const parts = [
    data.subject || '',
    headFrom.name || data.from_name || '',
    headFrom.mail_address || data.from_mail || '',
    data.body_preview || data.body_text || '',
  ];
  return parts.join('\n');
}

/**
 * 规则评分筛选候选团队。
 * @param {string} text - 邮件文本
 * @param {Array<Object>} teams - 团队数组
 * @returns {Array<Object>} 候选团队（含 score），按得分降序
 */
function _scoreCandidates(text, teams) {
  const candidates = [];
  for (let i = 0; i < teams.length; i++) {
    const team = teams[i];
    const rules = team.routing_rules || {};
    const pos = score(text, rules.positive_signals);
    const neg = score(text, rules.negative_signals);
    const net = pos - neg;
    if (net >= MIN_CANDIDATE_SCORE) {
      candidates.push(Object.assign({}, team, { score: net, positive_hits: pos, negative_hits: neg }));
    }
  }
  candidates.sort((a, b) => b.score - a.score);
  return candidates;
}

/**
 * 规则派单回退（LLM 不可用时使用）。
 * @param {Array<Object>} candidates - 候选团队
 * @returns {Object} dispatch 结果
 */
function _ruleBasedFallback(candidates) {
  const primary = candidates[0] || null;
  const primaryTeamKey = primary ? primary.team_key : '';
  const confidence = primary
    ? Math.max(35, Math.min(95, 55 + primary.score * 12))
    : 0;
  let risk = 'low';
  if (primary) {
    if (primary.score >= 3) risk = 'high';
    else if (primary.score >= 2) risk = 'medium';
  }
  const supporting = candidates
    .slice(1, 3)
    .map((c) => c.team_key)
    .filter(Boolean);
  return {
    business_type: primaryTeamKey,
    primary_team_key: primaryTeamKey,
    workflow_key: null,
    supporting_team_keys: supporting,
    risk_level: primary ? risk : 'unknown',
    confidence: confidence,
    reasons: primary
      ? [`基于关键词评分的规则派单（LLM 不可用），主理团队 ${primaryTeamKey} 得分 ${primary.score}`]
      : ['无候选团队命中关键词'],
    missing_information: [],
  };
}

/**
 * 规范化 LLM 返回结果，确保所有字段存在并类型正确。
 * @param {Object} raw - LLM 返回的结构化数据
 * @param {Array<Object>} candidates - 候选团队（用于校验 primary_team_key）
 * @returns {Object} 规范化后的 dispatch 结果
 */
function _normalizeResult(raw, candidates) {
  const data = raw || {};
  const validKeys = candidates.map((c) => c.team_key);
  let primary = data.primary_team_key;
  if (!primary || (validKeys.length > 0 && validKeys.indexOf(primary) === -1)) {
    // 主理团队不在候选内时回退到排名第一的候选
    primary = candidates[0] ? candidates[0].team_key : (primary || '');
  }
  const risk = data.risk_level;
  const validRisks = ['low', 'medium', 'high', 'critical', 'unknown'];
  const riskLevel = validRisks.indexOf(risk) !== -1 ? risk : 'unknown';
  let confidence = parseInt(data.confidence, 10);
  if (isNaN(confidence)) confidence = 0;
  confidence = Math.max(0, Math.min(100, confidence));
  const supporting = Array.isArray(data.supporting_team_keys)
    ? data.supporting_team_keys.filter((k) => typeof k === 'string' && k)
    : [];
  return {
    business_type: typeof data.business_type === 'string' ? data.business_type : (primary || ''),
    primary_team_key: primary,
    workflow_key: data.workflow_key == null ? null : String(data.workflow_key),
    supporting_team_keys: supporting,
    risk_level: riskLevel,
    confidence: confidence,
    reasons: Array.isArray(data.reasons) ? data.reasons.filter((r) => typeof r === 'string') : [],
    missing_information: Array.isArray(data.missing_information)
      ? data.missing_information.filter((r) => typeof r === 'string')
      : [],
  };
}

/**
 * 核心派单函数。
 * 1. 从 db 读取所有 active 团队的 routing_rules
 * 2. 对邮件文本评分筛选候选团队
 * 3. 调用 LLM API 传入邮件文本 + 候选团队 charter + dispatch schema
 * 4. 返回分类结果（primary_team_key / risk_level / confidence / supporting_team_keys 等）
 * LLM 不可用时回退到规则派单，保证流程不中断。
 * @param {Object} mailData - 邮件数据（含 subject/body_preview/head_from 等）
 * @returns {Promise<Object>} dispatch 结果
 */
async function proposeDispatch(mailData) {
  const text = _mailText(mailData);
  const teams = await _loadActiveTeams();
  const candidates = _scoreCandidates(text, teams).slice(0, MAX_CANDIDATE_TEAMS);

  if (candidates.length === 0) {
    logger.warn('dispatch.proposeDispatch: 无候选团队命中关键词，返回空派单');
    return {
      business_type: '',
      primary_team_key: '',
      workflow_key: null,
      supporting_team_keys: [],
      risk_level: 'unknown',
      confidence: 0,
      reasons: ['无候选团队命中关键词'],
      missing_information: ['无法识别邮件所属业务领域'],
    };
  }

  // 构造 LLM 输入：邮件文本 + 候选团队 charter
  const teamLines = candidates
    .map((c, idx) => {
      return (
        `${idx + 1}. team_key: ${c.team_key} | 名称: ${c.name} | 匹配得分: ${c.score} | 章程: ${c.charter}`
      );
    })
    .join('\n');
  const input =
    `邮件内容如下：\n${text}\n\n` +
    `候选团队（按关键词匹配得分排序）：\n${teamLines}\n\n` +
    `请基于邮件内容与候选团队章程，判断主理团队、协作团队、风险等级与置信度。` +
    `primary_team_key 必须从候选团队中选择。`;
  const instructions =
    '你是 WorkBuddy 派单助手。根据邮件内容与候选团队章程，按给定 JSON Schema 输出派单决策。' +
    '风险等级 high/critical 表示需要人工审批的高风险邮件。';

  try {
    const result = await llmClient.completeStructured(
      { instructions: instructions, input: input },
      dispatchSchema(),
      { schemaName: 'dispatch_decision' }
    );
    const normalized = _normalizeResult(result.data, candidates);
    logger.info(
      `dispatch.proposeDispatch: LLM 派单完成 primary=${normalized.primary_team_key} risk=${normalized.risk_level} confidence=${normalized.confidence}`
    );
    return normalized;
  } catch (err) {
    logger.warn(`dispatch.proposeDispatch: LLM 调用失败，回退规则派单 ${err.message}`);
    return _ruleBasedFallback(candidates);
  }
}

/**
 * 归一化风险等级到多维表格 missions 表支持的取值（base_schema 无 critical，映射为 high）。
 * @param {string} risk - 原始风险等级
 * @returns {string} 归一化后的风险等级（low/medium/high/unknown）
 */
function _storageRiskLevel(risk) {
  if (risk === 'low' || risk === 'medium' || risk === 'high') return risk;
  if (risk === 'critical') return 'high';
  return 'unknown';
}

/**
 * 创建 Mission 记录。
 * 1. 写入多维表格 missions 表
 * 2. 状态 = ROUTED
 * 3. 绑定团队、来源邮件、风险等级
 * @param {Object} dispatchResult - proposeDispatch 返回的派单结果
 * @param {Object} mailData - 邮件数据
 * @returns {Promise<Object>} 创建的 mission 记录（含 id 与各字段）
 */
async function createMission(dispatchResult, mailData) {
  const dispatch = dispatchResult || {};
  const mail = mailData || {};
  const messageId = mail.message_id || '';
  const subject = mail.subject || '(无主题)';
  const reasons = Array.isArray(dispatch.reasons) ? dispatch.reasons.join('；') : '';
  const objective = reasons || mail.body_preview || '';

  // 查询主理团队的主理人名称（用于 lead_agent_name）
  let leadAgentName = '';
  if (dispatch.primary_team_key) {
    try {
      const team = await db.queryOne(
        'SELECT lead_role_name FROM teams WHERE team_key = ? LIMIT 1',
        [dispatch.primary_team_key]
      );
      leadAgentName = (team && team.lead_role_name) || '';
    } catch (err) {
      logger.warn(`dispatch.createMission: 查询主理人名称失败 ${err.message}`);
    }
  }

  const fields = {
    title: subject,
    objective: objective,
    status: 'ROUTED',
    risk_level: _storageRiskLevel(dispatch.risk_level),
    source_type: 'mail',
    source_id: messageId,
    team_key: dispatch.primary_team_key || '',
    lead_agent_name: leadAgentName,
    created_at: _now(),
  };

  let insertResult;
  try {
    insertResult = await db.insert('missions', fields);
  } catch (err) {
    throw new Error(`dispatch.createMission: 写入 missions 表失败 ${err.message}`);
  }

  // 解析 mission id（兼容 insertId / id / 回查）
  let missionId = null;
  if (insertResult) {
    missionId = insertResult.insertId || insertResult.id || null;
  }
  if (!missionId && messageId) {
    try {
      const row = await db.queryOne(
        'SELECT id FROM missions WHERE source_id = ? ORDER BY id DESC LIMIT 1',
        [messageId]
      );
      missionId = (row && row.id) || null;
    } catch (err) {
      logger.warn(`dispatch.createMission: 回查 mission id 失败 ${err.message}`);
    }
  }

  const mission = Object.assign({ id: missionId }, fields, {
    risk_level: dispatch.risk_level || 'unknown',
  });
  logger.info(
    `dispatch.createMission: 已创建 mission id=${missionId} team=${fields.team_key} risk=${fields.risk_level}`
  );
  return mission;
}

/**
 * 创建协作请求。
 * 为每个 supporting_team_key 在 collaborations 表插入一条 PENDING 记录。
 * @param {string|number} missionId - 任务 ID
 * @param {Array<string>} supportingTeamKeys - 协作团队标识数组
 * @returns {Promise<number>} 创建的协作请求数量
 */
async function createCollaborationRequests(missionId, supportingTeamKeys) {
  if (!missionId) {
    logger.warn('dispatch.createCollaborationRequests: missionId 为空，跳过');
    return 0;
  }
  if (!Array.isArray(supportingTeamKeys) || supportingTeamKeys.length === 0) {
    return 0;
  }

  // 查询 mission 的主理团队与标题，作为协作请求的发起方与目标
  let fromTeamKey = '';
  let objective = '';
  try {
    const mission = await db.queryOne(
      'SELECT team_key, title FROM missions WHERE id = ? LIMIT 1',
      [missionId]
    );
    if (mission) {
      fromTeamKey = mission.team_key || '';
      objective = mission.title || '';
    }
  } catch (err) {
    logger.warn(`dispatch.createCollaborationRequests: 查询 mission 失败 ${err.message}`);
  }

  let created = 0;
  const now = _now();
  for (let i = 0; i < supportingTeamKeys.length; i++) {
    const toTeamKey = supportingTeamKeys[i];
    if (!toTeamKey || toTeamKey === fromTeamKey) continue;
    try {
      await db.insert('collaborations', {
        from_team_key: fromTeamKey,
        to_team_key: toTeamKey,
        objective: objective || '跨团队协作请求',
        expected_artifact: '',
        status: 'PENDING',
        created_at: now,
      });
      created++;
    } catch (err) {
      logger.warn(
        `dispatch.createCollaborationRequests: 创建协作请求失败 from=${fromTeamKey} to=${toTeamKey} ${err.message}`
      );
    }
  }
  logger.info(
    `dispatch.createCollaborationRequests: 已创建 ${created} 条协作请求 missionId=${missionId}`
  );
  return created;
}

/**
 * 发 IM 通知给主理人（发送任务到达通知卡片到 NOTIFY_CHAT_ID 群聊）。
 * @param {Object} missionData - 任务数据（含 id/team_key/title/risk_level/objective）
 * @returns {Promise<Object|null>} 发送结果；无 chatId 时返回 null
 */
async function notifyLead(missionData) {
  let chatId;
  try {
    chatId = await config.get('NOTIFY_CHAT_ID');
  } catch (err) {
    logger.warn(`dispatch.notifyLead: 读取 NOTIFY_CHAT_ID 失败 ${err.message}`);
    return null;
  }
  if (!chatId) {
    logger.warn('dispatch.notifyLead: 未配置 NOTIFY_CHAT_ID，跳过通知');
    return null;
  }

  let token;
  try {
    token = await oauth.getUserAccessToken();
  } catch (err) {
    logger.warn(`dispatch.notifyLead: 获取 user_access_token 失败 ${err.message}`);
    return null;
  }

  const card = feishuIm.buildTaskCard(missionData);
  try {
    const result = await feishuIm.sendCard(token, chatId, card);
    logger.info(
      `dispatch.notifyLead: 已通知主理人 chatId=${chatId} missionId=${missionData && missionData.id}`
    );
    return result;
  } catch (err) {
    logger.warn(`dispatch.notifyLead: 发送通知卡片失败 ${err.message}`);
    return null;
  }
}

module.exports = {
  score: score,
  dispatchSchema: dispatchSchema,
  proposeDispatch: proposeDispatch,
  createMission: createMission,
  createCollaborationRequests: createCollaborationRequests,
  notifyLead: notifyLead,
};
