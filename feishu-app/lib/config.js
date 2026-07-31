'use strict';

/**
 * WorkBuddy 配置读写模块。
 * 读写 config 表（key-value 结构），供 worker 运行参数管理使用。
 */

const db = require('./db');

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
    var row = await db.queryOne(
      'SELECT config_value FROM config WHERE config_key = ?',
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
 * 读取所有配置项。
 * @returns {Promise<Object>} { key: value } 对象
 * @throws {Error} 查询失败抛出含 message 的 Error
 */
async function getAll() {
  try {
    var rows = await db.queryAll('SELECT config_key, config_value FROM config', []);
    var result = {};
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
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
  var strValue = String(value);
  try {
    return await db.execute(
      'INSERT INTO config (config_key, config_value) VALUES (?, ?) ' +
        'ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)',
      [key, strValue]
    );
  } catch (err) {
    throw new Error(`config.set: 写入 key="${key}" 失败：${err.message}`);
  }
}

module.exports = {
  get: get,
  getAll: getAll,
  set: set,
};
