'use strict';

/**
 * WorkBuddy 配置读写模块。
 * 读写 config 表（key-value 结构），供 worker 运行参数管理使用。
 *
 * 仅依赖 Node.js 内置模块（通过 db.js 间接调用妙搭 OpenAPI），不依赖任何第三方库。
 *
 * config 表结构（见 schema.sql）：
 *   config_key   VARCHAR(64) PRIMARY KEY
 *   config_value TEXT
 *   updated_at   DATETIME
 */

const db = require('./db');
const { CONFIG_TABLE } = require('./constants');

/**
 * 读取单个配置项。
 * @param {string} key - 配置键名
 * @param {*} [defaultValue=null] - 键不存在时的返回值
 * @returns {Promise<string|null>} 配置值；不存在返回 defaultValue
 * @throws {Error} 查询失败抛出含 message + key 的 Error
 */
async function get(key, defaultValue) {
  if (defaultValue === undefined) defaultValue = null;
  if (!key || typeof key !== 'string') {
    throw new Error(`config.get: key 参数无效 (key=${key})`);
  }
  try {
    const row = await db.queryOne(
      `SELECT config_value FROM ${CONFIG_TABLE} WHERE config_key = ?`,
      [key]
    );
    if (!row) {
      return defaultValue;
    }
    return row.config_value != null ? row.config_value : defaultValue;
  } catch (err) {
    throw new Error(`config.get: 读取 key="${key}" 失败：${err.message}`);
  }
}

/**
 * 读取必填配置项。键不存在或值为空时抛出异常。
 * @param {string} key - 配置键名
 * @returns {Promise<string>} 配置值
 * @throws {Error} 键缺失或值为空时抛出含 key 的 Error
 */
async function getRequired(key) {
  if (!key || typeof key !== 'string') {
    throw new Error(`config.getRequired: key 参数无效 (key=${key})`);
  }
  const value = await get(key);
  if (value === null || value === undefined || value === '') {
    throw new Error(`config.getRequired: 必填配置缺失 (key="${key}")`);
  }
  return value;
}

/**
 * 读取所有配置项。
 * @returns {Promise<Object>} { key: value } 对象
 * @throws {Error} 查询失败抛出含 message 的 Error
 */
async function getAll() {
  try {
    const rows = await db.queryAll(
      `SELECT config_key, config_value FROM ${CONFIG_TABLE}`,
      []
    );
    const result = {};
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      result[row.config_key] = row.config_value;
    }
    return result;
  } catch (err) {
    throw new Error(`config.getAll: 读取全部配置失败：${err.message}`);
  }
}

/**
 * 设置配置项（UPSERT：存在则更新，不存在则插入）。
 * @param {string} key - 配置键名
 * @param {string} value - 配置值
 * @returns {Promise<Object>} 执行结果
 * @throws {Error} 写入失败抛出含 message + key 的 Error
 */
async function set(key, value) {
  if (!key || typeof key !== 'string') {
    throw new Error(`config.set: key 参数无效 (key=${key})`);
  }
  if (value == null) {
    throw new Error(`config.set: value 参数无效 (key=${key})`);
  }
  const strValue = String(value);
  try {
    return await db.execute(
      `INSERT INTO ${CONFIG_TABLE} (config_key, config_value) VALUES (?, ?) ` +
        `ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)`,
      [key, strValue]
    );
  } catch (err) {
    throw new Error(`config.set: 写入 key="${key}" 失败：${err.message}`);
  }
}

module.exports = {
  get: get,
  getRequired: getRequired,
  getAll: getAll,
  set: set,
};
