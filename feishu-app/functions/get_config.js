'use strict';

/**
 * WorkBuddy 配置查询云函数（HTML 控制台前端 GET 调用）。
 *
 * 查询 config 表全部记录，按 config_key 升序返回，供配置页回填表单。
 *
 * 入口签名说明：妙搭云函数入口约定为 exports.main = async (event, context) => {...}，
 * 本函数不依赖入参。
 *
 * 返回结构：
 *   {
 *     ok: true,
 *     data: {
 *       configs: Array<{ config_key, config_value, updated_at }>
 *     }
 *   }
 * 异常返回：{ ok: false, error: string }
 */

const db = require('../lib/db.js');
const logger = require('../lib/logger.js');
const { CONFIG_TABLE } = require('../lib/constants.js');

/**
 * 妙搭云函数入口：查询全部配置项。
 * @param {Object} [event] - 触发器事件（本函数不使用）
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: boolean, data?: { configs: [] }, error?: string }
 */
exports.main = async function (event, context) {
  try {
    // 查询全部配置，按 config_key 升序，便于前端稳定渲染
    const rows = await db.queryAll(
      `SELECT config_key, config_value, updated_at FROM ${CONFIG_TABLE} ORDER BY config_key ASC`,
      []
    );

    return {
      ok: true,
      data: {
        configs: Array.isArray(rows) ? rows : [],
      },
    };
  } catch (err) {
    logger.error(
      `get_config: 查询配置异常 err=${err && err.message ? err.message : err}`
    );
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
