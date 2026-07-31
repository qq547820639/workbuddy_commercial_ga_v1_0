'use strict';

/**
 * WorkBuddy 飞书自建应用 OAuth token 管理。
 * 管理 user_access_token 的获取、刷新、过期检查。
 *
 * token 存妙搭应用环境变量（process.env）：
 *   FEISHU_USER_ACCESS_TOKEN  — user_access_token
 *   FEISHU_USER_REFRESH_TOKEN — refresh_token
 *   FEISHU_TOKEN_EXPIRES_AT    — 过期时间戳（毫秒）
 *
 * 刷新接口：
 *   POST https://open.feishu.cn/open-apis/authen/v1/oidc/refresh_access_token
 *   body: { app_id, app_secret, grant_type: "refresh_token", refresh_token }
 */

const axios = require('axios');

/** 飞书 OpenAPI 基础地址（可按环境覆盖） */
const FEISHU_OPENAPI_BASE =
  process.env.FEISHU_OPENAPI_BASE || 'https://open.feishu.cn/open-apis';

/** 提前刷新的缓冲时间（毫秒），避免 token 刚好过期 */
const REFRESH_BUFFER_MS = 5 * 60 * 1000; // 5 分钟

/**
 * 保存 token 到环境变量（OAuth 回调后调用）。
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
  process.env.FEISHU_USER_ACCESS_TOKEN = accessToken;
  process.env.FEISHU_USER_REFRESH_TOKEN = refreshToken;
  process.env.FEISHU_TOKEN_EXPIRES_AT = String(expiresAt);
}

/**
 * 检查当前 token 是否已过期或即将过期（含缓冲时间）。
 * @returns {boolean} true 表示需要刷新
 */
function _isTokenExpired() {
  var expiresAt = parseInt(process.env.FEISHU_TOKEN_EXPIRES_AT || '0', 10);
  if (!expiresAt || isNaN(expiresAt)) {
    return true;
  }
  return Date.now() + REFRESH_BUFFER_MS >= expiresAt;
}

/**
 * 检查过期并刷新 token。
 * @param {boolean} [force=false] - true 表示强制刷新（不检查是否过期）
 * @returns {Promise<string>} 新的 user_access_token
 * @throws {Error} 刷新失败抛出含上下文的 Error
 */
async function refreshTokensIfNeeded(force) {
  if (force === undefined) force = false;

  // 非强制且 token 仍有效，无需刷新
  if (!force && !_isTokenExpired()) {
    var currentToken = process.env.FEISHU_USER_ACCESS_TOKEN;
    if (currentToken) {
      return currentToken;
    }
  }

  var appId = process.env.FEISHU_APP_ID;
  var appSecret = process.env.FEISHU_APP_SECRET;
  var refreshToken = process.env.FEISHU_USER_REFRESH_TOKEN;

  if (!appId) {
    throw new Error('feishu-oauth: 未设置环境变量 FEISHU_APP_ID');
  }
  if (!appSecret) {
    throw new Error('feishu-oauth: 未设置环境变量 FEISHU_APP_SECRET');
  }
  if (!refreshToken) {
    throw new Error('feishu-oauth: 未设置环境变量 FEISHU_USER_REFRESH_TOKEN，需先完成 OAuth 授权');
  }

  var url = `${FEISHU_OPENAPI_BASE}/authen/v1/oidc/refresh_access_token`;
  try {
    var resp = await axios.post(
      url,
      {
        app_id: appId,
        app_secret: appSecret,
        grant_type: 'refresh_token',
        refresh_token: refreshToken,
      },
      {
        headers: { 'Content-Type': 'application/json' },
        timeout: 10000,
      }
    );
    var body = resp.data || {};
    if (body.code !== undefined && body.code !== 0) {
      throw new Error(
        `feishu-oauth: 刷新 token 失败 code=${body.code} msg=${body.msg || ''}`
      );
    }
    var data = body.data || {};
    var newAccessToken = data.access_token;
    var newRefreshToken = data.refresh_token || refreshToken;
    var expiresIn = data.expires_in || data.expire_time || 7200;
    // expires_in 是秒，转为毫秒时间戳
    var expiresAt = Date.now() + expiresIn * 1000;

    if (!newAccessToken) {
      throw new Error('feishu-oauth: 刷新响应中缺少 access_token');
    }

    setTokens(newAccessToken, newRefreshToken, expiresAt);
    return newAccessToken;
  } catch (err) {
    // 已是带 feishu-oauth: 前缀的业务错误，直接抛
    if (err.message && err.message.indexOf('feishu-oauth:') !== -1) {
      throw err;
    }
    // axios HTTP 错误
    if (err.response) {
      var status = err.response.status;
      var respBody = err.response.data;
      throw new Error(
        `feishu-oauth: 刷新 token HTTP ${status} body=${JSON.stringify(respBody)}`
      );
    }
    throw new Error(`feishu-oauth: 刷新 token 失败：${err.message}`);
  }
}

/**
 * 获取有效的 user_access_token，过期自动用 refresh_token 刷新。
 * @returns {Promise<string>} 有效的 user_access_token
 * @throws {Error} 无可用 token 且刷新失败时抛出
 */
async function getUserAccessToken() {
  var token = process.env.FEISHU_USER_ACCESS_TOKEN;
  if (token && !_isTokenExpired()) {
    return token;
  }
  // token 缺失或过期，强制刷新
  return refreshTokensIfNeeded(true);
}

module.exports = {
  getUserAccessToken: getUserAccessToken,
  setTokens: setTokens,
  refreshTokensIfNeeded: refreshTokensIfNeeded,
};
