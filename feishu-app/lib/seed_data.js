'use strict';

/**
 * WorkBuddy 多维表格预填数据。
 *
 * 从 config/teams/*.yaml 提取的初始数据，供 init_base.js 在创建表后预填：
 *   - 5 个专家团队（团队表记录）
 *   - 每个团队的主理人与子角色智能体（智能体表记录）
 *   - 默认运行配置（配置表记录）
 *
 * 数据来源：
 *   - config/teams/customer_success.yaml
 *   - config/teams/finance_ops.yaml
 *   - config/teams/hr_people.yaml
 *   - config/teams/operations_delivery.yaml
 *   - config/teams/sales_growth.yaml
 *
 * 字段映射对照 feishu-app/lib/base_schema.js 中各表的 fields 定义。
 */

// ---------------------------------------------------------------------------
// 5 个专家团数据（对应 teams 表记录）
// ---------------------------------------------------------------------------

/**
 * 团队预填记录数组。每项字段对照 TEAMS_TABLE.fields：
 *   team_key / name / mission / active / lead_role_key / lead_role_name
 */
var TEAMS = [
  {
    team_key: 'customer_success',
    name: '客户成功与服务专家团',
    mission: '快速理解客户问题，协调解决路径，并以可追踪证据维护客户信任和长期价值。',
    active: true,
    lead_role_key: 'customer_success_director',
    lead_role_name: '客户成功主理人',
  },
  {
    team_key: 'finance_ops',
    name: '财务与运营专家团',
    mission: '处理财务与运营相关邮件，包括账款查询、发票、报销、预算、财务报表咨询，以合规和可追踪方式守护资金与数据边界。',
    active: true,
    lead_role_key: 'finance_director',
    lead_role_name: '财务主理人',
  },
  {
    team_key: 'hr_people',
    name: 'HR 与人事专家团',
    mission: '处理人力资源相关邮件，包括招聘、员工关系、薪酬福利咨询，以合规和可追踪方式维护员工与候选人信任。',
    active: true,
    lead_role_key: 'hr_director',
    lead_role_name: 'HR 主理人',
  },
  {
    team_key: 'operations_delivery',
    name: '运营与交付专家团',
    mission: '把交付风险、供应商沟通和跨部门问题转化为有负责人、有依赖、有证据的执行计划。',
    active: true,
    lead_role_key: 'delivery_director',
    lead_role_name: '交付主理人',
  },
  {
    team_key: 'sales_growth',
    name: '销售与商务增长专家团',
    mission: '将商业来信转化为可验证、可审批、可跟进的增长行动，同时保护利润和承诺边界。',
    active: true,
    lead_role_key: 'commercial_director',
    lead_role_name: '商务主理人',
  },
];

// ---------------------------------------------------------------------------
// 智能体数据（对应 agents 表记录）
// ---------------------------------------------------------------------------

/**
 * 辅助函数：拼接职责数组为逗号分隔字符串。
 * @param {Array<string>} arr - 职责数组
 * @returns {string} 逗号分隔字符串
 */
function _joinResp(arr) {
  if (!arr || !arr.length) return '';
  return arr.join(',');
}

/**
 * 智能体预填记录数组。每项字段对照 AGENTS_TABLE.fields：
 *   team_key / role_key / name / is_lead / status / responsibilities
 *
 * 来源：各团队 YAML 的 lead_role 与 default_workflows.work_items.role。
 * 主理人 is_lead = true，子角色 is_lead = false，status 默认 active。
 */
var AGENTS = [
  // 客户成功与服务专家团
  {
    team_key: 'customer_success',
    role_key: 'customer_success_director',
    name: '客户成功主理人',
    is_lead: true,
    status: 'active',
    responsibilities: _joinResp(['客户问题分级', '选择服务工作流', '协调技术与运营', '审核客户沟通', '管理升级']),
  },
  {
    team_key: 'customer_success',
    role_key: 'service_analyst',
    name: '服务分析师',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['客户问题分级与影响评估']),
  },
  {
    team_key: 'customer_success',
    role_key: 'resolution_coordinator',
    name: '解决方案协调员',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['收集解决证据', '制定恢复方案']),
  },
  {
    team_key: 'customer_success',
    role_key: 'customer_communicator',
    name: '客户沟通专员',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['客户沟通与回复起草']),
  },

  // 财务与运营专家团
  {
    team_key: 'finance_ops',
    role_key: 'finance_director',
    name: '财务主理人',
    is_lead: true,
    status: 'active',
    responsibilities: _joinResp(['邮件分级与归属确认', '选择标准工作流', '协调应收应付处理', '审核对外沟通', '管理升级与审批']),
  },
  {
    team_key: 'finance_ops',
    role_key: 'ar_specialist',
    name: '应收专员',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['应收账款处理', '发票咨询']),
  },
  {
    team_key: 'finance_ops',
    role_key: 'ap_specialist',
    name: '应付专员',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['应付账款处理', '付款申请处理']),
  },
  {
    team_key: 'finance_ops',
    role_key: 'finance_communicator',
    name: '财务沟通专员',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['财务对外沟通', '内部沟通起草']),
  },

  // HR 与人事专家团
  {
    team_key: 'hr_people',
    role_key: 'hr_director',
    name: 'HR 主理人',
    is_lead: true,
    status: 'active',
    responsibilities: _joinResp(['邮件分级与归属确认', '选择标准工作流', '协调招聘与员工关系', '审核对外沟通', '管理升级与审批']),
  },
  {
    team_key: 'hr_people',
    role_key: 'recruiter',
    name: '招聘专员',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['候选人筛选', '招聘流程咨询']),
  },
  {
    team_key: 'hr_people',
    role_key: 'relation_specialist',
    name: '员工关系专员',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['员工关系调查', '投诉处理']),
  },
  {
    team_key: 'hr_people',
    role_key: 'hr_communicator',
    name: 'HR 沟通专员',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['员工沟通', '候选人回复起草']),
  },

  // 运营与交付专家团
  {
    team_key: 'operations_delivery',
    role_key: 'delivery_director',
    name: '交付主理人',
    is_lead: true,
    status: 'active',
    responsibilities: _joinResp(['确认影响范围', '创建行动清单', '分配负责人', '管理依赖', '形成升级与审批材料']),
  },
  {
    team_key: 'operations_delivery',
    role_key: 'risk_analyst',
    name: '风险分析师',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['交付风险验证', '影响评估']),
  },
  {
    team_key: 'operations_delivery',
    role_key: 'delivery_planner',
    name: '交付规划师',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['恢复方案设计', '行动计划制定']),
  },
  {
    team_key: 'operations_delivery',
    role_key: 'coordination_specialist',
    name: '协调专员',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['事实收集', '利益相关方状态更新']),
  },

  // 销售与商务增长专家团
  {
    team_key: 'sales_growth',
    role_key: 'commercial_director',
    name: '商务主理人',
    is_lead: true,
    status: 'active',
    responsibilities: _joinResp(['接单与归属确认', '选择标准工作流', '创建任务清单与依赖', '整合商业、财务与法务意见', '向老板提交唯一审批包']),
  },
  {
    team_key: 'sales_growth',
    role_key: 'account_researcher',
    name: '客户研究员',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['客户背景研究', '商业需求提取']),
  },
  {
    team_key: 'sales_growth',
    role_key: 'deal_strategist',
    name: '商务策略师',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['商业场景分析', '谈判策略比较']),
  },
  {
    team_key: 'sales_growth',
    role_key: 'proposal_writer',
    name: '提案撰写专员',
    is_lead: false,
    status: 'active',
    responsibilities: _joinResp(['商务提案起草', '审批包准备']),
  },
];

// ---------------------------------------------------------------------------
// 默认配置（对应 config 表记录）
// ---------------------------------------------------------------------------

/**
 * 配置预填记录数组。每项字段对照 CONFIG_TABLE.fields：
 *   config_key / config_value / updated_at
 *
 * NOTIFY_CHAT_ID  — 通知目标群聊 chat_id（oc_ 开头）
 * POLL_INTERVAL   — 邮件轮询间隔（秒）
 * MAX_RECONNECT_BACKOFF — 指数退避上限（秒）
 */
var CONFIG_ROWS = [
  {
    config_key: 'NOTIFY_CHAT_ID',
    config_value: 'oc_716f4d911915d3e3d91a053e1a80f4a8',
    updated_at: null,
  },
  {
    config_key: 'POLL_INTERVAL',
    config_value: '60',
    updated_at: null,
  },
  {
    config_key: 'MAX_RECONNECT_BACKOFF',
    config_value: '300',
    updated_at: null,
  },
];

module.exports = {
  TEAMS: TEAMS,
  AGENTS: AGENTS,
  CONFIG_ROWS: CONFIG_ROWS,
};
