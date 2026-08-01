'use strict';

/**
 * WorkBuddy 飞书审批 OpenAPI 客户端。
 * 提供审批实例创建、审批状态查询、审批定义创建、审批表单构建能力。
 *
 * 飞书审批为应用级别操作，所有接口使用 tenant_access_token 鉴权
 * （由调用方通过 feishu-oauth.getTenantAccessToken 获取后传入）。
 *
 * 仅依赖 Node.js 内置模块（https/http/url），不依赖任何第三方库。
 *
 * 接口参考：
 *   - 创建审批实例：POST /approval/v4/instances
 *       body: { approval_code, form(表单 JSON 字符串) }
 *       resp: { code:0, data:{ instance_id } }
 *   - 查询审批状态：GET /approval/v4/instances/{instance_id}
 *       resp: { code:0, data:{ status: PENDING/APPROVED/REJECTED/CANCELED } }
 *   - 创建审批定义：POST /approval/v4/approvals
 *       body: { approval_code, name, form, node_list(审批人/抄送人) }
 *       resp: { code:0, data:{ approval_code } }
 */

const https = require('https');
const http = require('http');
const url = require('url');
const { FEISHU_OPENAPI_BASE, APPROVAL_TRIGGER_TYPES } = require('./constants');

/** 单次请求超时（毫秒） */
const REQUEST_TIMEOUT_MS = 15000;

/**
 * 审批触发类型 → 中文标签映射，用于审批表单展示。
 * 与 APPROVAL_TRIGGER_TYPES 保持一致。
 */
const TRIGGER_TYPE_LABELS = {
  refund: '退款',
  compensation: '补偿',
  legal_admission: '法律承认',
  resolution_commitment: '解决承诺',
  external_send: '外部发送',
};

/**
 * 用 Node.js 内置 https/http 模块发送 JSON 请求（支持 GET/POST）。
 * @param {string} method - HTTP 方法（GET/POST）
 * @param {string} requestUrl - 完整请求 URL
 * @param {Object} [body] - 请求体对象（GET 时传 undefined）
 * @param {Object} [headers] - 额外请求头
 * @param {number} [timeoutMs] - 超时毫秒
 * @returns {Promise<Object>} { statusCode, data, raw }，data 为已解析的 JSON
 * @throws {Error} 网络/超时抛出含上下文的 Error
 */
function _httpRequest(method, requestUrl, body, headers, timeoutMs) {
  return new Promise((resolve, reject) => {
    const parsed = url.parse(requestUrl);
    const isHttps = parsed.protocol === 'https:';
    const lib = isHttps ? https : http;
    const finalHeaders = Object.assign({}, headers || {});
    let payload = null;
    if (body !== undefined && body !== null) {
      payload = Buffer.from(JSON.stringify(body), 'utf8');
      finalHeaders['Content-Type'] = finalHeaders['Content-Type'] || 'application/json';
      finalHeaders['Content-Length'] = payload.length;
    }
    const options = {
      method: method,
      hostname: parsed.hostname,
      port: parsed.port || (isHttps ? 443 : 80),
      path: (parsed.pathname || '') + (parsed.search || ''),
      headers: finalHeaders,
    };
    const req = lib.request(options, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        const raw = Buffer.concat(chunks).toString('utf8');
        let parsedBody;
        try {
          parsedBody = raw ? JSON.parse(raw) : {};
        } catch (e) {
          parsedBody = raw;
        }
        resolve({ statusCode: res.statusCode, data: parsedBody, raw: raw });
      });
    });
    req.on('error', (err) => {
      reject(new Error(`网络请求失败 ${err.message}`));
    });
    if (timeoutMs && timeoutMs > 0) {
      req.setTimeout(timeoutMs, () => {
        req.destroy(new Error(`请求超时 (${timeoutMs}ms)`));
      });
    }
    if (payload) {
      req.write(payload);
    }
    req.end();
  });
}

/**
 * 解析飞书 API 响应信封，提取 data 字段。
 * @param {Object} resp - _httpRequest 返回的 { statusCode, data, raw }
 * @param {string} action - 操作描述（用于错误上下文）
 * @returns {Object} 飞书信封中的 data 字段
 * @throws {Error} HTTP 非 2xx 或业务 code 非 0 时抛出含 code + msg 的 Error
 */
function _parseResp(resp, action) {
  if (resp.statusCode < 200 || resp.statusCode >= 300) {
    const body = resp.data || {};
    const msg = (body && (body.msg || body.message)) || resp.raw || '';
    throw new Error(
      `feishu-approval: ${action} HTTP ${resp.statusCode} body=${msg}`
    );
  }
  const body = resp.data || {};
  if (body.code !== undefined && body.code !== 0) {
    throw new Error(
      `feishu-approval: ${action} 失败 code=${body.code} msg=${body.msg || ''}`
    );
  }
  return body.data != null ? body.data : body;
}

/**
 * 创建飞书审批实例。
 * @param {string} token - tenant_access_token
 * @param {string} approvalCode - 审批定义 code
 * @param {Object|string} formData - 表单数据对象（或已序列化的 JSON 字符串）
 * @returns {Promise<string>} 审批实例 ID（instance_id）
 * @throws {Error} 参数无效或飞书 API 失败时抛出含上下文的 Error
 */
async function createApproval(token, approvalCode, formData) {
  if (!token || typeof token !== 'string') {
    throw new Error('feishu-approval.createApproval: token 参数无效');
  }
  if (!approvalCode || typeof approvalCode !== 'string') {
    throw new Error(
      `feishu-approval.createApproval: approvalCode 参数无效 (approvalCode=${approvalCode})`
    );
  }
  // 飞书审批 API 要求 form 为 JSON 字符串
  const formStr =
    typeof formData === 'string' ? formData : JSON.stringify(formData || {});
  const requestUrl = `${FEISHU_OPENAPI_BASE}/approval/v4/instances`;
  let resp;
  try {
    resp = await _httpRequest(
      'POST',
      requestUrl,
      { approval_code: approvalCode, form: formStr },
      { Authorization: `Bearer ${token}` },
      REQUEST_TIMEOUT_MS
    );
  } catch (err) {
    throw new Error(`feishu-approval: 创建审批实例 ${err.message}`);
  }
  const data = _parseResp(resp, '创建审批实例');
  const instanceId = data.instance_id;
  if (!instanceId) {
    throw new Error('feishu-approval.createApproval: 响应中缺少 instance_id');
  }
  return instanceId;
}

/**
 * 查询审批实例状态。
 * @param {string} token - tenant_access_token
 * @param {string} instanceId - 审批实例 ID
 * @returns {Promise<string>} 审批状态（PENDING/APPROVED/REJECTED/CANCELED）
 * @throws {Error} 参数无效或飞书 API 失败时抛出含上下文的 Error
 */
async function getApprovalStatus(token, instanceId) {
  if (!token || typeof token !== 'string') {
    throw new Error('feishu-approval.getApprovalStatus: token 参数无效');
  }
  if (!instanceId || typeof instanceId !== 'string') {
    throw new Error(
      `feishu-approval.getApprovalStatus: instanceId 参数无效 (instanceId=${instanceId})`
    );
  }
  const requestUrl = `${FEISHU_OPENAPI_BASE}/approval/v4/instances/${encodeURIComponent(instanceId)}`;
  let resp;
  try {
    resp = await _httpRequest(
      'GET',
      requestUrl,
      undefined,
      { Authorization: `Bearer ${token}` },
      REQUEST_TIMEOUT_MS
    );
  } catch (err) {
    throw new Error(`feishu-approval: 查询审批状态 ${err.message}`);
  }
  const data = _parseResp(resp, '查询审批状态');
  // 飞书审批状态取值：PENDING / APPROVED / REJECTED / CANCELED / DELETED
  const status = data.status || data.approve_status || 'PENDING';
  return String(status).toUpperCase();
}

/**
 * 创建审批定义（一次性操作，含审批人、抄送人、表单字段）。
 * @param {string} token - tenant_access_token
 * @param {string} name - 审批定义名称
 * @param {Array} formFields - 表单字段定义数组，每项形如 { name, type, required, ... }
 * @returns {Promise<string>} 审批定义 code（approval_code）
 * @throws {Error} 参数无效或飞书 API 失败时抛出含上下文的 Error
 */
async function createApprovalDefinition(token, name, formFields) {
  if (!token || typeof token !== 'string') {
    throw new Error('feishu-approval.createApprovalDefinition: token 参数无效');
  }
  if (!name || typeof name !== 'string') {
    throw new Error(
      `feishu-approval.createApprovalDefinition: name 参数无效 (name=${name})`
    );
  }
  const fields = Array.isArray(formFields) ? formFields : [];
  const requestUrl = `${FEISHU_OPENAPI_BASE}/approval/v4/approvals`;
  // 构造审批定义：表单字段 + 审批人节点 + 抄送人节点
  const body = {
    approval_code: `WORKBUDDY_${Date.now()}`,
    name: name,
    description: `WorkBuddy 自动创建审批定义 - ${name}`,
    form: JSON.stringify({ fields: fields }),
    // 审批流程节点：审批人节点 + 抄送人节点
    node_list: [
      {
        type: 'APPROVE',
        name: '审批人',
        node_approver: [],
      },
      {
        type: 'CC',
        name: '抄送人',
        node_cc: [],
      },
    ],
    approval_method: 'AND',
  };
  let resp;
  try {
    resp = await _httpRequest(
      'POST',
      requestUrl,
      body,
      { Authorization: `Bearer ${token}` },
      REQUEST_TIMEOUT_MS
    );
  } catch (err) {
    throw new Error(`feishu-approval: 创建审批定义 ${err.message}`);
  }
  const data = _parseResp(resp, '创建审批定义');
  return data.approval_code || data.approval_id || '';
}

/**
 * 构建审批表单数据。
 * 表单包含：任务标题、团队、风险等级、操作类型、操作描述、触发类型、任务 ID。
 * @param {Object} missionData - Mission 数据（含 title/team_key/risk_level/objective 等）
 * @param {string} triggerType - 审批触发类型，取值见 APPROVAL_TRIGGER_TYPES
 * @returns {Object} 审批表单数据对象（键为中文表单控件名）
 * @throws {Error} 参数无效或 triggerType 不在 APPROVAL_TRIGGER_TYPES 中时抛出
 */
function buildApprovalForm(missionData, triggerType) {
  if (!missionData || typeof missionData !== 'object') {
    throw new Error('feishu-approval.buildApprovalForm: missionData 参数无效');
  }
  // 校验 triggerType 在 APPROVAL_TRIGGER_TYPES 中
  const validTypes = Object.keys(APPROVAL_TRIGGER_TYPES).map(function (k) {
    return APPROVAL_TRIGGER_TYPES[k];
  });
  if (validTypes.indexOf(triggerType) === -1) {
    throw new Error(
      `feishu-approval.buildApprovalForm: triggerType 无效 (triggerType=${triggerType})`
    );
  }
  return {
    任务标题: missionData.title || '(未命名任务)',
    团队: missionData.team_key || missionData.team || '',
    风险等级: missionData.risk_level || '',
    操作类型: TRIGGER_TYPE_LABELS[triggerType] || triggerType,
    操作描述: missionData.objective || missionData.description || '',
    触发类型: triggerType,
    任务ID: missionData.id || missionData.mission_id || '',
  };
}

module.exports = {
  createApproval: createApproval,
  getApprovalStatus: getApprovalStatus,
  createApprovalDefinition: createApprovalDefinition,
  buildApprovalForm: buildApprovalForm,
};
