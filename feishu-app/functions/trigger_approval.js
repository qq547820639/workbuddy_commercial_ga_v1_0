'use strict';

/**
 * WorkBuddy 触发飞书审批云函数。
 *
 * 业务流程：高风险操作 → 触发飞书审批 → 写审批请求记录 → Mission 进入待审批 → 通知审批人。
 *
 * 步骤：
 *   1. 校验 event.mission_id / event.trigger_type（trigger_type 必须在 APPROVAL_TRIGGER_TYPES 中）
 *   2. 查询 Mission
 *   3. 获取 tenant_access_token（审批为应用级操作）
 *   4. 读取审批定义 code（优先 APPROVAL_CODE_{TRIGGER_TYPE}，回退 APPROVAL_CODE）
 *   5. 构建审批表单（feishu-approval.buildApprovalForm）
 *   6. 创建飞书审批实例（feishu-approval.createApproval）
 *   7. 写入 approvals 表
 *   8. Mission 状态 → APPROVAL_REQUIRED
 *   9. 发 IM 通知审批人
 *   10. 返回 { ok: true, approval_instance_id }
 *
 * 入口签名：exports.main = async (event, context) => {...}
 * event: { mission_id, trigger_type }
 */

const db = require('../lib/db.js');
const logger = require('../lib/logger.js');
const config = require('../lib/config.js');
const oauth = require('../lib/feishu-oauth.js');
const {
  MISSION_STATUS,
  APPROVAL_TRIGGER_TYPES,
} = require('../lib/constants.js');
const feishuApproval = require('../lib/feishu-approval.js');
const externalActions = require('../lib/external_actions.js');

/**
 * Mission 状态扩展。
 * constants.MISSION_STATUS 仅含基础状态，审批闭环需要的状态（与
 * base_schema.js MISSION_STATUS_OPTIONS 一致）在此补充。
 */
const EXT_MISSION_STATUS = Object.assign({}, MISSION_STATUS, {
  APPROVAL_REQUIRED: 'APPROVAL_REQUIRED',
  APPROVED: 'APPROVED',
  ACTION_EXECUTING: 'ACTION_EXECUTING',
  VERIFYING: 'VERIFYING',
  BLOCKED: 'BLOCKED',
});

/**
 * 当前时间格式化为 'YYYY-MM-DD HH:MM:SS'。
 * @returns {string} 格式化后的时间字符串
 */
function _nowStr() {
  const d = new Date();
  const pad = function (n) {
    return n < 10 ? '0' + n : '' + n;
  };
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

/**
 * 构造审批待办通知卡片（Card 2.0）。
 * @param {Object} mission - Mission 数据
 * @param {string} triggerType - 触发类型
 * @param {string} instanceId - 审批实例 ID
 * @returns {Object} 卡片 JSON
 */
function _buildApproverCard(mission, triggerType, instanceId) {
  return {
    schema: '2.0',
    config: { update_multi: true, width_mode: 'default' },
    header: {
      title: { tag: 'plain_text', content: '审批待办：WorkBuddy 高风险操作' },
      template: 'orange',
    },
    body: {
      direction: 'vertical',
      padding: '12px 12px 20px 12px',
      elements: [
        {
          tag: 'div',
          text: { tag: 'lark_md', content: `**任务**：${mission.title || '(未命名)'}` },
        },
        {
          tag: 'div',
          text: { tag: 'lark_md', content: `**触发类型**：${triggerType}` },
        },
        {
          tag: 'div',
          text: { tag: 'lark_md', content: `**风险等级**：${mission.risk_level || '未知'}` },
        },
        {
          tag: 'div',
          text: { tag: 'lark_md', content: `**审批实例**：${instanceId}` },
        },
      ],
    },
  };
}

/**
 * 发送 IM 通知审批人。失败只记日志，不抛异常。
 * @param {Object} mission - Mission 数据
 * @param {string} triggerType - 触发类型
 * @param {string} instanceId - 审批实例 ID
 * @returns {Promise<void>}
 */
async function _notifyApprovers(mission, triggerType, instanceId) {
  try {
    const chatId = await config.get('NOTIFY_CHAT_ID');
    if (!chatId) {
      logger.warn('trigger_approval: 未配置 NOTIFY_CHAT_ID，跳过审批人通知');
      return;
    }
    const token = await oauth.getUserAccessToken();
    const card = _buildApproverCard(mission, triggerType, instanceId);
    await externalActions.sendIM(token, chatId, card);
  } catch (err) {
    logger.error(
      `trigger_approval: 通知审批人失败 err=${err && err.message ? err.message : err}`
    );
  }
}

/**
 * 妙搭云函数入口：触发飞书审批。
 * @param {Object} event - 触发参数 { mission_id, trigger_type }
 * @param {Object} [context] - 调用元信息（本函数不使用）
 * @returns {Promise<Object>} { ok: true, approval_instance_id } 或 { ok: false, error }
 */
exports.main = async function (event, context) {
  try {
    const missionId = event && event.mission_id;
    const triggerType = event && event.trigger_type;

    // 1. 参数校验
    if (!missionId) {
      return { ok: false, error: '缺少 mission_id' };
    }
    if (!triggerType) {
      return { ok: false, error: '缺少 trigger_type' };
    }
    // 校验 trigger_type 是否在 APPROVAL_TRIGGER_TYPES 中
    const validTypes = Object.keys(APPROVAL_TRIGGER_TYPES).map(function (k) {
      return APPROVAL_TRIGGER_TYPES[k];
    });
    if (validTypes.indexOf(triggerType) === -1) {
      return {
        ok: false,
        error: `trigger_type 无效 (trigger_type=${triggerType})，合法值: ${validTypes.join('/')}`,
      };
    }

    // 2. 查询 Mission
    let mission;
    try {
      mission = await db.queryOne(
        'SELECT * FROM missions WHERE id = ? LIMIT 1',
        [missionId]
      );
    } catch (err) {
      logger.error(
        `trigger_approval: 查询 Mission 失败 mission=${missionId} err=${err.message}`
      );
      return { ok: false, error: `查询 Mission 失败：${err.message}` };
    }
    if (!mission) {
      return { ok: false, error: `Mission 不存在: ${missionId}` };
    }

    // 3. 获取 tenant_access_token（审批为应用级操作）
    const appId = process.env.FEISHU_APP_ID;
    const appSecret = process.env.FEISHU_APP_SECRET;
    if (!appId || !appSecret) {
      return {
        ok: false,
        error: '未配置环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET',
      };
    }
    let tenantToken;
    try {
      tenantToken = await oauth.getTenantAccessToken(appId, appSecret);
    } catch (err) {
      logger.error(`trigger_approval: 获取 tenant_access_token 失败 err=${err.message}`);
      return { ok: false, error: `获取 tenant_access_token 失败：${err.message}` };
    }

    // 4. 读取审批定义 code（优先按触发类型，回退到默认）
    const triggerKey = `APPROVAL_CODE_${triggerType.toUpperCase()}`;
    let approvalCode = await config.get(triggerKey);
    if (!approvalCode) {
      approvalCode = await config.get('APPROVAL_CODE');
    }
    if (!approvalCode) {
      return {
        ok: false,
        error: `未配置审批定义 code (${triggerKey} 或 APPROVAL_CODE)`,
      };
    }

    // 5. 构建审批表单
    const formData = feishuApproval.buildApprovalForm(mission, triggerType);

    // 6. 创建飞书审批实例
    let instanceId;
    try {
      instanceId = await feishuApproval.createApproval(
        tenantToken,
        approvalCode,
        formData
      );
    } catch (err) {
      logger.error(
        `trigger_approval: 创建审批实例失败 mission=${missionId} err=${err.message}`
      );
      return { ok: false, error: `创建审批实例失败：${err.message}` };
    }
    logger.info(
      `trigger_approval: 已创建审批实例 ${instanceId} (mission=${missionId}, trigger=${triggerType})`
    );

    // 7. 写入 approvals 表
    try {
      await db.insert('approvals', {
        mission_id: missionId,
        trigger_type: triggerType,
        status: 'PENDING',
        approval_instance_id: instanceId,
        created_at: _nowStr(),
      });
    } catch (err) {
      // 写表失败不阻断（审批实例已创建），仅记日志
      logger.error(
        `trigger_approval: 写 approvals 表失败 instance=${instanceId} err=${err.message}`
      );
    }

    // 8. Mission 状态 → APPROVAL_REQUIRED
    try {
      await db.execute(
        'UPDATE missions SET status = ? WHERE id = ?',
        [EXT_MISSION_STATUS.APPROVAL_REQUIRED, missionId]
      );
      logger.info(
        `trigger_approval: Mission ${missionId} 状态 → ${EXT_MISSION_STATUS.APPROVAL_REQUIRED}`
      );
    } catch (err) {
      logger.error(
        `trigger_approval: 更新 Mission 状态失败 mission=${missionId} err=${err.message}`
      );
    }

    // 9. 发 IM 通知审批人
    await _notifyApprovers(mission, triggerType, instanceId);

    // 10. 返回审批实例 ID
    return { ok: true, approval_instance_id: instanceId };
  } catch (err) {
    logger.error(
      `trigger_approval: 异常 err=${err && err.message ? err.message : err}`
    );
    return {
      ok: false,
      error: err && err.message ? err.message : String(err),
    };
  }
};
