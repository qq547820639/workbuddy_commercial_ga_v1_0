'use strict';

/**
 * WorkBuddy 配置保存云函数（HTML 控制台前端 POST 调用）。
 *
 * 入口签名说明：妙搭云函数入口约定为 exports.main = async (event, context) => {...}，
 * 具体 event / context 形态需在妙搭环境验证；POST body 从 event.body 读，
 * 可能是字符串需 JSON.parse，也可能是对象。
 *
 * 入参（从 event.body 读 JSON）：
 *   {
 *     config_key:   string,  // 配置键名，必填
 *     config_value: string   // 配置值，必填
 *   }
 *
 * 执行流程：
 *   1. 校验 config_key 非空
 *   2. 用 lib/config.js 的 set 方法 UPSERT（INSERT ... ON DUPLICATE KEY UPDATE）
 *   3. logger.info 记录配置变更
 *   4. 返回 { ok: true, data: { config_key, config_value } }
 *
 * 异常返回：{ ok: false, error: string }
 */

const config = require('../lib/config.js');
const logger = require('../lib/logger.js');

/**
 * 从 event 解析入参，兼容两种形态：
 *   1. 妙搭 HTTP 触发：event.body 为 JSON 字符串或对象（标准形态）
 *   2. 直接调用：event.config_key / event.config_value 挂在 event 顶层
 *      （对应任务约定的 event.config_key, event.config_value 入参）
 * @param {Object} event - 妙搭事件对象
 * @returns {{config_key: string, config_value: string}}
 * @throws {Error} body 缺失或非对象/JSON 时抛出
 */
function _parseBody(event) {
  let body = event && event.body;
  if (body != null) {
    if (typeof body === 'string') {
      if (body.trim() === '') {
        body = null;
      } else {
        try {
          body = JSON.parse(body);
        } catch (e) {
          throw new Error(`update_config: event.body JSON 解析失败：${e.message}`);
        }
      }
    }
    if (body != null && (typeof body !== 'object' || Array.isArray(body))) {
      throw new Error('update_config: event.body 不是 JSON 对象');
    }
  }
  // 回退：event 顶层 config_key / config_value（直接调用场景）
  if (
    !body &&
    event &&
    (event.config_key != null || event.config_value != null)
  ) {
    body = {
      config_key: event.config_key,
      config_value: event.config_value,
    };
  }
  if (!body) {
    throw new Error('update_config: event.body 缺失');
  }
  return body;
}

/**
 * 妙搭云函数入口：保存配置项。
 * @param {Object} [event] - 触发器事件
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: boolean, data?: {...}, error?: string }
 */
exports.main = async function (event, context) {
  try {
    // 1. 解析 body
    const body = _parseBody(event);

    // 2. 校验 config_key 非空
    const configKey =
      body.config_key != null ? String(body.config_key).trim() : '';
    if (!configKey) {
      throw new Error('update_config: config_key 不能为空');
    }
    if (body.config_value == null) {
      throw new Error(
        `update_config: config_value 不能为空 (config_key=${configKey})`
      );
    }
    const configValue = String(body.config_value);

    // 3. UPSERT 写入 config 表
    await config.set(configKey, configValue);

    // 4. 记录配置变更日志
    logger.info(
      `update_config: 配置已更新 key=${configKey} value_len=${configValue.length}`
    );

    return {
      ok: true,
      data: {
        config_key: configKey,
        config_value: configValue,
      },
    };
  } catch (err) {
    logger.error(
      `update_config: 保存配置异常 err=${err && err.message ? err.message : err}`
    );
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
