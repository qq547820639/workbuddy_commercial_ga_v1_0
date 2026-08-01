'use strict';

/**
 * WorkBuddy 飞书任务（Task）OpenAPI 客户端。
 * 提供飞书任务的创建、状态更新、子任务创建能力。
 *
 * 仅依赖 Node.js 内置模块（https/http/url），不依赖任何第三方库。
 * 所有接口用 user_access_token 鉴权（由调用方传入）。
 *
 * 飞书任务 API 参考：
 *   - 创建任务：POST /task/v2/tasks
 *   - 更新任务：PATCH /task/v2/tasks/{task_id}
 *   - 任务状态字段：status（枚举 todo/doing/done/cancelled）
 *
 * 错误处理：抛出含 status + body 上下文的 Error。
 */

const https = require('https');
const http = require('http');
const url = require('url');
const { FEISHU_OPENAPI_BASE } = require('./constants');

/** 单次请求超时（毫秒） */
const REQUEST_TIMEOUT_MS = 15000;

/**
 * 用 Node.js 内置 https/http 模块发送 HTTP 请求。
 * @param {string} method - HTTP 方法（POST/PATCH/GET）
 * @param {string} requestUrl - 完整请求 URL
 * @param {Object} [body] - 请求体对象（将 JSON 序列化），无请求体时传 undefined
 * @param {Object} headers - 额外请求头
 * @param {number} timeoutMs - 超时毫秒
 * @returns {Promise<Object>} { statusCode, data, raw }
 * @throws {Error} 网络/超时抛出含上下文的 Error
 */
function _httpRequest(method, requestUrl, body, headers, timeoutMs) {
  return new Promise((resolve, reject) => {
    const parsed = url.parse(requestUrl);
    const isHttps = parsed.protocol === 'https:';
    const lib = isHttps ? https : http;
    const payload = body !== undefined ? Buffer.from(JSON.stringify(body), 'utf8') : null;
    const finalHeaders = Object.assign(
      {
        'Content-Type': 'application/json',
      },
      headers || {}
    );
    if (payload !== null) {
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
      reject(new Error(`feishu-task: 网络请求失败 ${err.message}`));
    });
    if (timeoutMs && timeoutMs > 0) {
      req.setTimeout(timeoutMs, () => {
        req.destroy(new Error(`feishu-task: 请求超时 (${timeoutMs}ms)`));
      });
    }
    if (payload !== null) {
      req.write(payload);
    }
    req.end();
  });
}

/**
 * 校验飞书 API 响应信封，提取业务 data。
 * @param {Object} resp - _httpRequest 返回的 { statusCode, data, raw }
 * @param {string} action - 操作描述（用于错误上下文）
 * @returns {Object} 飞书信封中的 data 字段
 * @throws {Error} HTTP 非 2xx 或业务 code 非 0 时抛出含 code + msg 的 Error
 */
function _parseResponse(resp, action) {
  if (resp.statusCode < 200 || resp.statusCode >= 300) {
    const body = resp.data || {};
    const msg = (body && (body.msg || body.message)) || resp.raw || '';
    throw new Error(
      `feishu-task: ${action} HTTP ${resp.statusCode} body=${msg}`
    );
  }
  const body = resp.data || {};
  if (body.code !== undefined && body.code !== 0) {
    throw new Error(
      `feishu-task: ${action} 失败 code=${body.code} msg=${body.msg || ''}`
    );
  }
  return body.data != null ? body.data : body;
}

/**
 * 创建飞书任务。
 * @param {string} token - user_access_token
 * @param {string} title - 任务标题
 * @param {string} [description] - 任务描述（可选）
 * @param {string} [parentId] - 父任务 ID（可选，传入则创建子任务）
 * @returns {Promise<Object>} 创建结果（含 task_guid / task_id 等）
 * @throws {Error} 参数无效或 API 失败抛出含上下文的 Error
 */
async function createTask(token, title, description, parentId) {
  if (!token || typeof token !== 'string') {
    throw new Error(`feishu-task.createTask: token 参数无效`);
  }
  if (!title || typeof title !== 'string') {
    throw new Error(`feishu-task.createTask: title 参数无效 (title=${title})`);
  }
  const requestBody = {
    summary: title,
    description: description || '',
  };
  // 传入 parentId 则标记为子任务
  if (parentId) {
    requestBody.parent_task_id = parentId;
  }
  const requestUrl = `${FEISHU_OPENAPI_BASE}/task/v2/tasks`;
  const resp = await _httpRequest(
    'POST',
    requestUrl,
    requestBody,
    { Authorization: `Bearer ${token}` },
    REQUEST_TIMEOUT_MS
  );
  return _parseResponse(resp, '创建任务');
}

/**
 * 更新飞书任务状态。
 * 飞书任务状态枚举：todo（待处理）/ doing（进行中）/ done（已完成）/ cancelled（已取消）。
 * @param {string} token - user_access_token
 * @param {string} taskId - 任务 ID（task_guid）
 * @param {string} status - 目标状态（todo/doing/done/cancelled）
 * @returns {Promise<Object>} 更新结果
 * @throws {Error} 参数无效或 API 失败抛出含上下文的 Error
 */
async function updateTaskStatus(token, taskId, status) {
  if (!token || typeof token !== 'string') {
    throw new Error(`feishu-task.updateTaskStatus: token 参数无效`);
  }
  if (!taskId || typeof taskId !== 'string') {
    throw new Error(`feishu-task.updateTaskStatus: taskId 参数无效 (taskId=${taskId})`);
  }
  const validStatuses = ['todo', 'doing', 'done', 'cancelled'];
  if (validStatuses.indexOf(status) === -1) {
    throw new Error(
      `feishu-task.updateTaskStatus: status 参数无效 (status=${status})，必须为 ${validStatuses.join('/')}`
    );
  }
  const requestUrl = `${FEISHU_OPENAPI_BASE}/task/v2/tasks/${encodeURIComponent(taskId)}`;
  const resp = await _httpRequest(
    'PATCH',
    requestUrl,
    { status: status },
    { Authorization: `Bearer ${token}` },
    REQUEST_TIMEOUT_MS
  );
  return _parseResponse(resp, '更新任务状态');
}

/**
 * 创建飞书子任务。
 * @param {string} token - user_access_token
 * @param {string} parentId - 父任务 ID（task_guid）
 * @param {string} title - 子任务标题
 * @param {string} [description] - 子任务描述（可选）
 * @returns {Promise<Object>} 创建结果（含 task_guid / task_id 等）
 * @throws {Error} 参数无效或 API 失败抛出含上下文的 Error
 */
async function createSubTask(token, parentId, title, description) {
  if (!token || typeof token !== 'string') {
    throw new Error(`feishu-task.createSubTask: token 参数无效`);
  }
  if (!parentId || typeof parentId !== 'string') {
    throw new Error(`feishu-task.createSubTask: parentId 参数无效 (parentId=${parentId})`);
  }
  if (!title || typeof title !== 'string') {
    throw new Error(`feishu-task.createSubTask: title 参数无效 (title=${title})`);
  }
  return createTask(token, title, description, parentId);
}

module.exports = {
  createTask: createTask,
  updateTaskStatus: updateTaskStatus,
  createSubTask: createSubTask,
};
