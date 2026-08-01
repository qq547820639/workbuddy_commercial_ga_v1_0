'use strict';

/**
 * WorkBuddy 飞书自建应用 OAuth token 管理。
 * 管理 tenant_access_token / user_access_token 的获取、刷新、过期检查。
 *
 * 仅依赖 Node.js 内置模块（https/http/url），不依赖任何第三方库。
 * token 持久化通过 config.js 读写 config 表（妙搭环境变量），同时在 process.env 做内存缓存。
 *
 * 飞书 OAuth 接口：
 *   - tenant_access_token：POST /auth/v3/tenant_access_token/internal
 *       body: { app_id, app_secret }
 *       resp: { code:0, tenant_access_token, expire }
 *   - user_access_token（授权码换）：POST /authen/v1/oidc/access_token
 *       body: { app_id, app_secret, grant_type:"authorization_code", code }
 *       resp: { code:0, data:{ access_token, refresh_token, expires_in } }
 *   - refresh_access_token：POST /authen/v1/oidc/refresh_access_token
 *       body: { app_id, app_secret, grant_type:"refresh_token", refresh_token }
 *       resp: { code:0, data:{ access_token, refresh_token, expires_in } }
 *
 * 缓存 key（同时用于 process.env 与 config 表）：
 *   FEISHU_USER_ACCESS_TOKEN   — user_access_token
 *   FEISHU_USER_REFRESH_TOKEN  — refresh_token
 *   FEISHU_TOKEN_EXPIRES_AT    — user_access_token 过期时间戳（毫秒）
 * tenant_access_token 仅内存缓存（FEISHU_TENANT_ACCESS_TOKEN / _EXPIRES_AT）。
 */

const https = require('https');
const http = require('http');
const url = require('url');
const config = require('./config');
const { FEISHU_OPENAPI_BASE } = require('./constants');

/** 提前刷新的缓冲时间（毫秒），避免 token 刚好过期 */
const REFRESH_BUFFER_MS = 5 * 60 * 1000; // 5 分钟

/** 单次 OAuth 请求超时（毫秒） */
const REQUEST_TIMEOUT_MS = 10000;

/** token 在 config 表 / process.env 中的缓存 key */
const TOKEN_KEY_AT = 'FEISHU_USER_ACCESS_TOKEN';
const TOKEN_KEY_RT = 'FEISHU_USER_REFRESH_TOKEN';
const TOKEN_KEY_EXP = 'FEISHU_TOKEN_EXPIRES_AT';

/** tenant_access_token 内存缓存 key */
const TENANT_TOKEN_KEY = 'FEISHU_TENANT_ACCESS_TOKEN';
const TENANT_TOKEN_EXP_KEY = 'FEISHU_TENANT_ACCESS_TOKEN_EXPIRES_AT';

/**
 * 用 Node.js 内置 https/http 模块发送 JSON POST 请求。
 * @param {string} requestUrl - 完整请求 URL
 * @param {Object} body - 请求体对象（将 JSON 序列化）
 * @param {Object} [headers] - 额外请求头
 * @param {number} [timeoutMs] - 超时毫秒
 * @returns {Promise<Object>} { statusCode, data }，data 为已解析的 JSON
 * @throws {Error} 网络/超时抛出含上下文的 Error
 */
function _httpPost(requestUrl, body, headers, timeoutMs) {
  return new Promise((resolve, reject) => {
    const parsed = url.parse(requestUrl);
    const isHttps = parsed.protocol === 'https:';
    const lib = isHttps ? https : http;
    const payload = Buffer.from(JSON.stringify(body || {}), 'utf8');
    const finalHeaders = Object.assign(
      {
        'Content-Type': 'application/json',
        'Content-Length': payload.length,
      },
      headers || {}
    );
    const options = {
      method: 'POST',
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
    req.write(payload);
    req.end();
  });
}

/**
 * 校验飞书 OAuth 响应信封，提取业务 data。
 * @param {Object} resp - _httpPost 返回的 { statusCode, data, raw }
 * @param {string} action - 操作描述（用于错误上下文）
 * @param {boolean} dataWrapped - true 表示业务数据在 data 字段；false 表示业务数据在顶层
 * @returns {Object} 业务数据对象
 * @throws {Error} HTTP 非 2xx 或业务 code 非 0 时抛出含 code + msg 的 Error
 */
function _parseOAuthResponse(resp, action, dataWrapped) {
  if (resp.statusCode < 200 || resp.statusCode >= 300) {
    const body = resp.data || {};
    const msg = (body && (body.msg || body.message)) || resp.raw || '';
    throw new Error(
      `feishu-oauth: ${action} HTTP ${resp.statusCode} body=${msg}`
    );
  }
  const body = resp.data || {};
  if (body.code !== undefined && body.code !== 0) {
    throw new Error(
      `feishu-oauth: ${action} 失败 code=${body.code} msg=${body.msg || ''}`
    );
  }
  return dataWrapped ? (body.data || {}) : body;
}

/**
 * 从 config 表加载 user token 到 process.env 内存缓存。
 * 已在内存中的不会被覆盖（除非 force）。
 * @param {boolean} [force=false] - true 表示强制从 config 表重新加载
 * @returns {Promise<void>}
 */
async function _loadUserTokensFromConfig(force) {
  if (force === undefined) force = false;
  try {
    if (force || !process.env[TOKEN_KEY_AT]) {
      const at = await config.get(TOKEN_KEY_AT);
      if (at) process.env[TOKEN_KEY_AT] = at;
    }
    if (force || !process.env[TOKEN_KEY_RT]) {
      const rt = await config.get(TOKEN_KEY_RT);
      if (rt) process.env[TOKEN_KEY_RT] = rt;
    }
    if (force || !process.env[TOKEN_KEY_EXP]) {
      const exp = await config.get(TOKEN_KEY_EXP);
      if (exp) process.env[TOKEN_KEY_EXP] = exp;
    }
  } catch (err) {
    // 读取失败只记 console，不阻断（调用方会在 token 缺失时抛错）
    console.error(`[feishu-oauth] 从 config 表加载 token 失败：${err.message}`);
  }
}

/**
 * 保存 user token 到 process.env 内存 + config 表（持久化）。
 * 持久化失败只 console.error，不阻断（内存已更新）。
 * @param {string} accessToken - user_access_token
 * @param {string} refreshToken - refresh_token
 * @param {number} expiresAt - 过期时间戳（毫秒）
 * @returns {Promise<void>}
 */
async function _saveUserTokens(accessToken, refreshToken, expiresAt) {
  process.env[TOKEN_KEY_AT] = accessToken;
  process.env[TOKEN_KEY_RT] = refreshToken;
  process.env[TOKEN_KEY_EXP] = String(expiresAt);
  try {
    await config.set(TOKEN_KEY_AT, accessToken);
    await config.set(TOKEN_KEY_RT, refreshToken);
    await config.set(TOKEN_KEY_EXP, String(expiresAt));
  } catch (err) {
    console.error(`[feishu-oauth] token 持久化到 config 表失败：${err.message}`);
  }
}

/**
 * 检查当前 user_access_token 是否已过期或即将过期（含缓冲时间）。
 * @returns {boolean} true 表示需要刷新
 */
function _isUserTokenExpired() {
  const expiresAt = parseInt(process.env[TOKEN_KEY_EXP] || '0', 10);
  if (!expiresAt || isNaN(expiresAt)) {
    return true;
  }
  return Date.now() + REFRESH_BUFFER_MS >= expiresAt;
}

/**
 * 获取 tenant_access_token（用 app_id + app_secret 换）。
 * 内存缓存有效期内直接返回，过期自动重新获取。
 * @param {string} appId - 飞书自建应用 app_id
 * @param {string} appSecret - 飞书自建应用 app_secret
 * @returns {Promise<string>} tenant_access_token
 * @throws {Error} 获取失败（网络错误/飞书 API 错误）抛出含上下文的 Error
 */
async function getTenantAccessToken(appId, appSecret) {
  if (!appId || typeof appId !== 'string') {
    throw new Error(`feishu-oauth.getTenantAccessToken: appId 参数无效 (appId=${appId})`);
  }
  if (!appSecret || typeof appSecret !== 'string') {
    throw new Error(`feishu-oauth.getTenantAccessToken: appSecret 参数无效`);
  }
  // 内存缓存有效，直接返回
  const cached = process.env[TENANT_TOKEN_KEY];
  const cachedExp = parseInt(process.env[TENANT_TOKEN_EXP_KEY] || '0', 10);
  if (cached && cachedExp && Date.now() + REFRESH_BUFFER_MS < cachedExp) {
    return cached;
  }
  const requestUrl = `${FEISHU_OPENAPI_BASE}/auth/v3/tenant_access_token/internal`;
  let resp;
  try {
    resp = await _httpPost(
      requestUrl,
      { app_id: appId, app_secret: appSecret },
      { 'Content-Type': 'application/json' },
      REQUEST_TIMEOUT_MS
    );
  } catch (err) {
    throw new Error(`feishu-oauth: 获取 tenant_access_token ${err.message}`);
  }
  // tenant_access_token 响应业务数据在顶层（无 data 包裹）
  const body = _parseOAuthResponse(resp, '获取 tenant_access_token', false);
  const token = body.tenant_access_token;
  if (!token) {
    throw new Error('feishu-oauth: 获取 tenant_access_token 响应中缺少 tenant_access_token');
  }
  const expire = body.expire || 7200;
  process.env[TENANT_TOKEN_KEY] = token;
  process.env[TENANT_TOKEN_EXP_KEY] = String(Date.now() + expire * 1000);
  return token;
}

/**
 * 用授权码换 user_access_token（OAuth 回调时调用）。
 *
 * 兼容用法：无参数调用时返回缓存的 user_access_token（过期自动刷新），
 * 供 feishu-im.js / feishu-mail.js 等模块获取可用 token 使用。
 *
 * @param {string} [appId] - 飞书自建应用 app_id（用授权码换时必填）
 * @param {string} [appSecret] - 飞书自建应用 app_secret（用授权码换时必填）
 * @param {string} [code] - OAuth 授权码（用授权码换时必填）
 * @returns {Promise<string>} user_access_token
 * @throws {Error} 换取失败（网络错误/飞书 API 错误/授权码无效）抛出含上下文的 Error
 */
async function getUserAccessToken(appId, appSecret, code) {
  // 无参数：返回缓存的 user_access_token（过期自动刷新）
  if (arguments.length === 0) {
    return _getCachedUserAccessToken();
  }
  // 有参数：用授权码换 user_access_token
  if (!appId || typeof appId !== 'string') {
    throw new Error(`feishu-oauth.getUserAccessToken: appId 参数无效 (appId=${appId})`);
  }
  if (!appSecret || typeof appSecret !== 'string') {
    throw new Error('feishu-oauth.getUserAccessToken: appSecret 参数无效');
  }
  if (!code || typeof code !== 'string') {
    throw new Error(`feishu-oauth.getUserAccessToken: code 参数无效 (code=${code})`);
  }
  const requestUrl = `${FEISHU_OPENAPI_BASE}/authen/v1/oidc/access_token`;
  let resp;
  try {
    resp = await _httpPost(
      requestUrl,
      {
        app_id: appId,
        app_secret: appSecret,
        grant_type: 'authorization_code',
        code: code,
      },
      { 'Content-Type': 'application/json' },
      REQUEST_TIMEOUT_MS
    );
  } catch (err) {
    throw new Error(`feishu-oauth: 用授权码换 user_access_token ${err.message}`);
  }
  const data = _parseOAuthResponse(resp, '用授权码换 user_access_token', true);
  const accessToken = data.access_token;
  const refreshToken = data.refresh_token;
  const expiresIn = data.expires_in || data.expire_time || 7200;
  if (!accessToken) {
    throw new Error('feishu-oauth: 授权码换取响应中缺少 access_token');
  }
  const expiresAt = Date.now() + expiresIn * 1000;
  await _saveUserTokens(accessToken, refreshToken, expiresAt);
  return accessToken;
}

/**
 * 用 refresh_token 刷新 user_access_token。
 * @param {string} appId - 飞书自建应用 app_id
 * @param {string} appSecret - 飞书自建应用 app_secret
 * @param {string} refreshToken - refresh_token
 * @returns {Promise<string>} 新的 user_access_token
 * @throws {Error} 刷新失败（网络错误/飞书 API 错误/refresh_token 失效）抛出含上下文的 Error
 */
async function refreshUserToken(appId, appSecret, refreshToken) {
  if (!appId || typeof appId !== 'string') {
    throw new Error(`feishu-oauth.refreshUserToken: appId 参数无效 (appId=${appId})`);
  }
  if (!appSecret || typeof appSecret !== 'string') {
    throw new Error('feishu-oauth.refreshUserToken: appSecret 参数无效');
  }
  if (!refreshToken || typeof refreshToken !== 'string') {
    throw new Error(`feishu-oauth.refreshUserToken: refreshToken 参数无效`);
  }
  const requestUrl = `${FEISHU_OPENAPI_BASE}/authen/v1/oidc/refresh_access_token`;
  let resp;
  try {
    resp = await _httpPost(
      requestUrl,
      {
        app_id: appId,
        app_secret: appSecret,
        grant_type: 'refresh_token',
        refresh_token: refreshToken,
      },
      { 'Content-Type': 'application/json' },
      REQUEST_TIMEOUT_MS
    );
  } catch (err) {
    throw new Error(`feishu-oauth: 刷新 user_access_token ${err.message}`);
  }
  const data = _parseOAuthResponse(resp, '刷新 user_access_token', true);
  const accessToken = data.access_token;
  const newRefreshToken = data.refresh_token || refreshToken;
  const expiresIn = data.expires_in || data.expire_time || 7200;
  if (!accessToken) {
    throw new Error('feishu-oauth: 刷新响应中缺少 access_token');
  }
  const expiresAt = Date.now() + expiresIn * 1000;
  await _saveUserTokens(accessToken, newRefreshToken, expiresAt);
  return accessToken;
}

/**
 * 获取缓存的 user_access_token，过期自动用 refresh_token 刷新。
 * 内存无缓存时先从 config 表加载。
 * @returns {Promise<string>} 有效的 user_access_token
 * @throws {Error} 无可用 token 且刷新失败时抛出含上下文的 Error
 */
async function _getCachedUserAccessToken() {
  let token = process.env[TOKEN_KEY_AT];
  // 内存无缓存，尝试从 config 表加载
  if (!token) {
    await _loadUserTokensFromConfig(true);
    token = process.env[TOKEN_KEY_AT];
  }
  if (token && !_isUserTokenExpired()) {
    return token;
  }
  // token 缺失或过期，强制刷新
  return refreshTokensIfNeeded(true);
}

/**
 * 检查过期并刷新 user_access_token（向后兼容方法）。
 * 供 feishu-im.js / feishu-mail.js 在 401 重试时调用。
 * @param {boolean} [force=false] - true 表示强制刷新（不检查是否过期）
 * @returns {Promise<string>} 有效的 user_access_token
 * @throws {Error} 刷新失败抛出含上下文的 Error
 */
async function refreshTokensIfNeeded(force) {
  if (force === undefined) force = false;
  // 非强制且 token 仍有效，无需刷新
  if (!force && !_isUserTokenExpired()) {
    const currentToken = process.env[TOKEN_KEY_AT];
    if (currentToken) {
      return currentToken;
    }
  }
  const appId = process.env.FEISHU_APP_ID;
  const appSecret = process.env.FEISHU_APP_SECRET;
  let refreshToken = process.env[TOKEN_KEY_RT];
  // 内存无 refresh_token，尝试从 config 表加载
  if (!refreshToken) {
    await _loadUserTokensFromConfig(true);
    refreshToken = process.env[TOKEN_KEY_RT];
  }
  if (!appId) {
    throw new Error('feishu-oauth: 未设置环境变量 FEISHU_APP_ID');
  }
  if (!appSecret) {
    throw new Error('feishu-oauth: 未设置环境变量 FEISHU_APP_SECRET');
  }
  if (!refreshToken) {
    throw new Error('feishu-oauth: 无 refresh_token，需先完成 OAuth 授权');
  }
  return refreshUserToken(appId, appSecret, refreshToken);
}

/**
 * 保存 user token 到内存 + config 表（OAuth 回调后调用，向后兼容方法）。
 * 同步设置内存缓存，异步 fire-and-forget 持久化到 config 表。
 * @param {string} accessToken - user_access_token
 * @param {string} refreshToken - refresh_token
 * @param {number} expiresAt - 过期时间戳（毫秒）
 * @returns {void}
 */
function setTokens(accessToken, refreshToken, expiresAt) {
  if (!accessToken || typeof accessToken !== 'string') {
    throw new Error(`feishu-oauth.setTokens: accessToken 参数无效 (accessToken=${accessToken})`);
  }
  if (!refreshToken || typeof refreshToken !== 'string') {
    throw new Error(`feishu-oauth.setTokens: refreshToken 参数无效 (refreshToken=${refreshToken})`);
  }
  if (typeof expiresAt !== 'number' || expiresAt <= 0) {
    throw new Error(`feishu-oauth.setTokens: expiresAt 参数无效 (expiresAt=${expiresAt})`);
  }
  // 同步设置内存缓存
  process.env[TOKEN_KEY_AT] = accessToken;
  process.env[TOKEN_KEY_RT] = refreshToken;
  process.env[TOKEN_KEY_EXP] = String(expiresAt);
  // fire-and-forget 持久化到 config 表
  _saveUserTokens(accessToken, refreshToken, expiresAt).catch(function (err) {
    console.error(`[feishu-oauth] setTokens 持久化失败：${err.message}`);
  });
}

module.exports = {
  getTenantAccessToken: getTenantAccessToken,
  getUserAccessToken: getUserAccessToken,
  refreshUserToken: refreshUserToken,
  setTokens: setTokens,
  refreshTokensIfNeeded: refreshTokensIfNeeded,
};
