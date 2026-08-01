'use strict';

/**
 * WorkBuddy 飞书多维表格初始化云函数（妙搭）。
 *
 * 一次性初始化脚本，通过飞书 Bitable OpenAPI 创建 Base + 全部 12 张表 + 字段，
 * 并预填团队、智能体、配置数据。
 *
 * 链路：
 *   1. 获取 user_access_token（feishu-oauth.js）
 *   2. 创建 Base（Bitable 应用），拿到 app_token
 *   3. 逐张建表（含全部字段），拿到 table_id
 *   4. 预填 teams / agents / config 表记录
 *   5. 返回 app_token + 各 table_id
 *
 * 入口签名：exports.main = async (event, context) => {...}
 *   - event.name 可选覆盖 Base 名称
 *   - context 为妙搭调用元信息
 *
 * 鉴权：user_access_token，需应用具备 bitable:app 权限。
 */

var axios = require('axios');
var oauth = require('../lib/feishu-oauth.js');
var schema = require('../lib/base_schema.js');
var seed = require('../lib/seed_data.js');

/** 飞书 OpenAPI 基础地址（可按环境覆盖） */
var FEISHU_OPENAPI_BASE =
  process.env.FEISHU_OPENAPI_BASE || 'https://open.feishu.cn/open-apis';

/** 默认 Base 名称（与 feishu/base_init.py BASE_NAME 一致） */
var DEFAULT_BASE_NAME = 'WorkBuddy数据层';

/** 单次请求超时（毫秒），建表/批写较慢，给足时间 */
var REQUEST_TIMEOUT = 30000;

/** 批量创建记录上限（飞书单次 batch_create 最多 500 条） */
var BATCH_CREATE_LIMIT = 500;

/**
 * 日志输出（妙搭云函数日志会收集 console.log）。
 * @param {string} msg - 日志消息
 */
function _log(msg) {
  console.log('[init_base] ' + msg);
}

/**
 * 调用飞书 Bitable OpenAPI，带 401 自动刷新重试。
 * @param {string} method - HTTP 方法（POST/GET/PUT）
 * @param {string} path - API 路径（不含 base，如 /bitable/v1/apps）
 * @param {Object} [body] - 请求体
 * @returns {Promise<Object>} 飞书信封中的 data 字段
 * @throws {Error} 含 status + code + msg + path 的 Error
 */
async function _feishuRequest(method, path, body) {
  var token = await oauth.getUserAccessToken();
  var url = FEISHU_OPENAPI_BASE + path;
  var config = {
    method: method,
    url: url,
    headers: { 'Authorization': 'Bearer ' + token },
    timeout: REQUEST_TIMEOUT,
  };
  if (body !== undefined) {
    config.data = body;
    config.headers['Content-Type'] = 'application/json';
  }

  try {
    var resp = await axios(config);
    return _parseResponse(resp, url);
  } catch (err) {
    // 401 → 强制刷新 token 后重试一次
    if (err.response && err.response.status === 401) {
      _log('token 过期（401），刷新后重试：' + url);
      await oauth.refreshTokensIfNeeded(true);
      token = await oauth.getUserAccessToken();
      config.headers['Authorization'] = 'Bearer ' + token;
      try {
        var resp2 = await axios(config);
        return _parseResponse(resp2, url);
      } catch (retryErr) {
        throw _wrapError(retryErr, url);
      }
    }
    throw _wrapError(err, url);
  }
}

/**
 * 解析飞书 API 响应，提取 data 字段。
 * @param {Object} resp - axios 响应对象
 * @param {string} url - 请求 URL（错误上下文）
 * @returns {Object} 飞书信封中的 data 字段
 * @throws {Error} 业务码非 0 时抛出含 code + msg + url 的 Error
 */
function _parseResponse(resp, url) {
  var body = resp.data || {};
  if (body.code !== undefined && body.code !== 0) {
    throw new Error(
      'init_base: API 失败 code=' + body.code + ' msg=' + (body.msg || '') + '; url=' + url
    );
  }
  return body.data != null ? body.data : body;
}

/**
 * 将错误包装为含 status + body 上下文的 Error。
 * @param {Error} err - 原始错误
 * @param {string} url - 请求 URL
 * @returns {Error} 包装后的 Error
 */
function _wrapError(err, url) {
  if (err.message && err.message.indexOf('init_base:') !== -1) {
    return err;
  }
  if (err.response) {
    var status = err.response.status;
    var respBody = err.response.data;
    return new Error(
      'init_base: HTTP ' + status + ' body=' + JSON.stringify(respBody) + '; url=' + url
    );
  }
  return new Error('init_base: ' + err.message + '; url=' + url);
}

/**
 * 将 base_schema 的字段定义转换为飞书建表 API 所需的 field 定义。
 * select 类型附带 property.options；datetime 类型附带日期格式。
 * @param {Array} fields - base_schema 中的 fields 数组
 * @returns {Array} 飞书 field 定义数组（{ field_name, type, property? }）
 */
function _buildFieldDefs(fields) {
  var typeCodeMap = schema.FIELD_TYPE_CODE_MAP;
  var defs = [];
  for (var i = 0; i < fields.length; i++) {
    var f = fields[i];
    var typeCode = typeCodeMap[f.type];
    if (typeCode === undefined) {
      _log('警告：未知字段类型 ' + f.type + '，按 text(1) 处理：' + f.name);
      typeCode = 1;
    }
    var def = { field_name: f.name, type: typeCode };
    // select 类型需要附带可选值
    if (f.type === 'select' && f.options) {
      def.property = { options: f.options };
    }
    // datetime 类型附带日期格式（ yyyy/MM/dd HH:mm ）
    if (f.type === 'datetime') {
      def.property = { date_formatter: 'yyyy/MM/dd HH:mm' };
    }
    defs.push(def);
  }
  return defs;
}

/**
 * 创建一个飞书 Base（Bitable 应用）。
 * @param {string} name - Base 名称
 * @returns {Promise<string>} app_token（Base 的唯一标识）
 * @throws {Error} 创建失败抛出
 */
async function createBase(name) {
  _log('创建 Base：' + name);
  var data = await _feishuRequest('POST', '/bitable/v1/apps', { name: name });
  var appToken = data.app && data.app.app_token;
  if (!appToken) {
    throw new Error('init_base: 创建 Base 未返回 app_token，响应：' + JSON.stringify(data));
  }
  _log('Base 创建成功 app_token=' + appToken);
  return appToken;
}

/**
 * 在指定 Base 中创建一张表（含全部字段）。
 * @param {string} appToken - Base 的 app_token
 * @param {Object} tableDef - base_schema 中的表定义（含 tableKey/name/fields）
 * @returns {Promise<string>} table_id
 * @throws {Error} 创建失败抛出
 */
async function createTable(appToken, tableDef) {
  var fieldDefs = _buildFieldDefs(tableDef.fields);
  _log('建表：' + tableDef.name + '（' + fieldDefs.length + ' 字段）');
  var body = {
    table: {
      name: tableDef.name,
      default_view_name: tableDef.name + '视图',
      fields: fieldDefs,
    },
  };
  var data = await _feishuRequest(
    'POST',
    '/bitable/v1/apps/' + appToken + '/tables',
    body
  );
  var tableId = data.table_id || (data.table && data.table.table_id);
  if (!tableId) {
    throw new Error(
      'init_base: 建表[' + tableDef.name + ']未返回 table_id，响应：' + JSON.stringify(data)
    );
  }
  _log('  ' + tableDef.name + ' table_id=' + tableId);
  return tableId;
}

/**
 * 将预填记录的字段值转换为飞书多维表格兼容类型。
 *   checkbox → boolean
 *   datetime → 毫秒时间戳（null 跳过）
 *   select   → 字符串（选项名）
 *   number   → 数字
 *   text     → 字符串
 * @param {Object} tableDef - 表 schema 定义（含 fields，用于查字段类型）
 * @param {Object} record - 预填记录（字段名 → 值）
 * @returns {Object} 飞书 fields 对象（仅含非空字段）
 */
function _convertRecordFields(tableDef, record) {
  // 构建字段名 → 类型 索引
  var typeIndex = {};
  for (var i = 0; i < tableDef.fields.length; i++) {
    var fld = tableDef.fields[i];
    typeIndex[fld.name] = fld.type;
  }
  var fields = {};
  var keys = Object.keys(record);
  for (var j = 0; j < keys.length; j++) {
    var key = keys[j];
    var val = record[key];
    var ftype = typeIndex[key] || 'text';

    // null/undefined 值跳过（飞书不允许写空值到部分类型）
    if (val === null || val === undefined) {
      continue;
    }

    if (ftype === 'checkbox') {
      fields[key] = val ? true : false;
    } else if (ftype === 'datetime') {
      // 字符串时间或 Date 转毫秒时间戳
      if (val instanceof Date) {
        fields[key] = val.getTime();
      } else if (typeof val === 'number') {
        fields[key] = val;
      } else if (typeof val === 'string' && val) {
        var ts = Date.parse(val);
        fields[key] = isNaN(ts) ? Date.now() : ts;
      } else {
        fields[key] = Date.now();
      }
    } else if (ftype === 'number') {
      fields[key] = Number(val) || 0;
    } else {
      // text / select / url → 字符串
      fields[key] = String(val);
    }
  }
  return fields;
}

/**
 * 批量创建记录到指定表。
 * @param {string} appToken - Base 的 app_token
 * @param {string} tableId - 目标表 ID
 * @param {Object} tableDef - 表 schema 定义（用于字段类型转换）
 * @param {Array} records - 预填记录数组
 * @returns {Promise<number>} 成功写入的记录数
 */
async function batchCreateRecords(appToken, tableId, tableDef, records) {
  if (!records || records.length === 0) {
    return 0;
  }
  var count = 0;
  // 分批，每批最多 BATCH_CREATE_LIMIT 条
  for (var i = 0; i < records.length; i += BATCH_CREATE_LIMIT) {
    var batch = records.slice(i, i + BATCH_CREATE_LIMIT);
    var reqRecords = [];
    for (var j = 0; j < batch.length; j++) {
      reqRecords.push({
        fields: _convertRecordFields(tableDef, batch[j]),
      });
    }
    var path = '/bitable/v1/apps/' + appToken + '/tables/' + tableId + '/records/batch_create';
    var data = await _feishuRequest('POST', path, { records: reqRecords });
    var written = (data.records && data.records.length) || batch.length;
    count += written;
  }
  return count;
}

/**
 * 妙搭云函数入口：初始化 WorkBuddy 数据层 Base。
 * @param {Object} [event] - 触发事件；event.name 可覆盖 Base 名称
 * @param {Object} [context] - 调用元信息
 * @returns {Promise<Object>} { ok, data: { app_token, table_ids, seeded }, error? }
 */
exports.main = async function (event, context) {
  var baseName = (event && event.name) || DEFAULT_BASE_NAME;
  _log('开始初始化 WorkBuddy 数据层，Base 名称：' + baseName);
  _log('共 ' + schema.ALL_TABLES.length + ' 张表');

  var tableIds = {};
  var seeded = {};
  try {
    // 1. 创建 Base
    var appToken = await createBase(baseName);

    // 2. 逐张建表
    for (var i = 0; i < schema.ALL_TABLES.length; i++) {
      var tableDef = schema.ALL_TABLES[i];
      var tableId = await createTable(appToken, tableDef);
      tableIds[tableDef.tableKey] = tableId;
    }
    _log('全部 ' + schema.ALL_TABLES.length + ' 张表创建完成');

    // 3. 预填团队数据
    var teamsTableId = tableIds['teams'];
    if (teamsTableId) {
      var n = await batchCreateRecords(
        appToken, teamsTableId, schema.TEAMS_TABLE, seed.TEAMS
      );
      seeded.teams = n;
      _log('预填团队 ' + n + ' 条');
    }

    // 4. 预填智能体数据
    var agentsTableId = tableIds['agents'];
    if (agentsTableId) {
      var m = await batchCreateRecords(
        appToken, agentsTableId, schema.AGENTS_TABLE, seed.AGENTS
      );
      seeded.agents = m;
      _log('预填智能体 ' + m + ' 条');
    }

    // 5. 预填默认配置
    var configTableId = tableIds['config'];
    if (configTableId) {
      var k = await batchCreateRecords(
        appToken, configTableId, schema.CONFIG_TABLE, seed.CONFIG_ROWS
      );
      seeded.config = k;
      _log('预填配置 ' + k + ' 条');
    }

    _log('初始化完成');
    return {
      ok: true,
      data: {
        app_token: appToken,
        base_name: baseName,
        table_ids: tableIds,
        seeded: seeded,
      },
    };
  } catch (err) {
    _log('初始化失败：' + (err && err.message ? err.message : err));
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
      data: {
        table_ids: tableIds,
        seeded: seeded,
      },
    };
  }
};
