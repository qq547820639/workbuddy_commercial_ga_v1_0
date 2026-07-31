'use strict';

/**
 * WorkBuddy Worker 启停控制云函数（HTML 控制台前端 POST 调用）。
 *
 * 入口签名说明：妙搭云函数入口约定为 exports.main = async (event, context) => {...}，
 * 具体 event / context 形态需在妙搭环境验证；POST body 从 event.body 读，
 * 可能是字符串需 JSON.parse，也可能是对象。
 *
 * 入参（从 event.body 读 JSON）：
 *   { action: "start" | "stop" }
 *
 * 执行流程：
 *   1. action="start"：调妙搭 API 启用自动触发任务；
 *      action="stop"：调妙搭 API 禁用自动触发任务
 *   2. 妙搭 API 调用方式用注释占位（见下方 TODO）
 *   3. 更新 worker_status 表的 is_running 字段
 *   4. logger.info 记录启停动作
 *   5. 返回 { ok: true, data: { is_running: boolean, action: string } }
 *
 * 异常返回：{ ok: false, error: string }
 */

const db = require('../lib/db.js');
const logger = require('../lib/logger.js');

/**
 * 从 event.body 解析 JSON 入参，兼容字符串和对象两种形态。
 * @param {Object} event - 妙搭事件对象
 * @returns {{action: string}}
 * @throws {Error} body 缺失或非对象/JSON 时抛出
 */
function _parseBody(event) {
  let body = event && event.body;
  if (body == null) {
    throw new Error('control_worker: event.body 缺失');
  }
  if (typeof body === 'string') {
    if (body.trim() === '') {
      throw new Error('control_worker: event.body 为空字符串');
    }
    try {
      body = JSON.parse(body);
    } catch (e) {
      throw new Error(`control_worker: event.body JSON 解析失败：${e.message}`);
    }
  }
  if (typeof body !== 'object' || Array.isArray(body)) {
    throw new Error('control_worker: event.body 不是 JSON 对象');
  }
  return body;
}

/**
 * 调用妙搭 API 启用/禁用自动触发任务。
 *
 * TODO: 妙搭自动触发任务 API 调用方式需在妙搭环境验证
 * 预期调用：apps +automation-enable / +automation-disable
 * 当前无法用 lark-cli 自动化，需用户在妙搭 Web 控制台手动配置
 *
 * @param {string} action - "start" 或 "stop"
 * @returns {Promise<void>} 当前为占位实现，直接 resolve
 */
async function _callMiaodaAutomation(action) {
  // TODO: 妙搭自动触发任务 API 调用方式需在妙搭环境验证
  // 预期调用：apps +automation-enable / +automation-disable
  // 当前无法用 lark-cli 自动化，需用户在妙搭 Web 控制台手动配置
  //
  // 伪代码示例（实际接口名/路径/鉴权需在妙搭环境确认）：
  //   if (action === 'start') {
  //     await axios.post(`${MIAODA_API_BASE}/v1/apps/${appId}/automation-enable`);
  //   } else {
  //     await axios.post(`${MIAODA_API_BASE}/v1/apps/${appId}/automation-disable`);
  //   }
  logger.warn(
    `control_worker: 妙搭自动触发任务 API 未实现（action=${action}），需用户在妙搭 Web 控制台手动${action === 'start' ? '启用' : '禁用'}`
  );
}

/**
 * 妙搭云函数入口：启停 worker。
 * @param {Object} [event] - 触发器事件
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: boolean, data?: {...}, error?: string }
 */
exports.main = async function (event, context) {
  try {
    // 1. 解析 body
    const body = _parseBody(event);

    // 2. 校验 action
    const action =
      body.action != null ? String(body.action).trim().toLowerCase() : '';
    if (action !== 'start' && action !== 'stop') {
      throw new Error(
        `control_worker: action 参数无效 (action=${body.action})，必须为 start/stop`
      );
    }

    // 3. 调妙搭 API 启停自动触发任务（占位实现）
    await _callMiaodaAutomation(action);

    // 4. 更新 worker_status 表的 is_running 字段
    const isRunning = action === 'start';
    await db.execute(
      'UPDATE worker_status SET is_running = ? WHERE id = 1',
      [isRunning ? 1 : 0]
    );

    // 5. 记录启停动作
    logger.info(
      `control_worker: worker 已${isRunning ? '启动' : '停止'} (action=${action})`
    );

    return {
      ok: true,
      data: {
        is_running: isRunning,
        action: action,
      },
    };
  } catch (err) {
    logger.error(
      `control_worker: 启停 worker 异常 err=${err && err.message ? err.message : err}`
    );
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
