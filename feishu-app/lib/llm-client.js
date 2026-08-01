'use strict';

/**
 * WorkBuddy LLM 调用共享库。
 * 通过 OpenAI Responses API 调用大模型并返回结构化 JSON 结果。
 *
 * 仅依赖 Node.js 内置模块（https），不依赖任何第三方库。
 * API Key 从 config.getRequired('LLM_API_KEY') 获取；
 * model 默认 "gpt-4o"，可从 config.get('LLM_MODEL') 覆盖。
 *
 * OpenAI Responses API：
 *   POST https://api.openai.com/v1/responses
 *   body: {
 *     model, instructions, input,
 *     response_format: { type: "json_schema", json_schema: { name, strict, schema } }
 *   }
 *   resp: { output: [{ type:"message", content:[{ type:"output_text", text:"{...}" }] }],
 *           output_text: "..." (便捷字段，可能存在),
 *           usage: { input_tokens, output_tokens, total_tokens } }
 *
 * 错误处理：API 错误（非 2xx）、网络错误、JSON 解析错误均抛出含上下文的 Error。
 */

const https = require('https');
const config = require('./config');

/** OpenAI API 基础地址（可按环境覆盖，如自建网关） */
const OPENAI_API_BASE =
  process.env.OPENAI_API_BASE || 'https://api.openai.com';

/** 默认模型 */
const DEFAULT_MODEL = 'gpt-4o';

/** 单次请求超时（毫秒） */
const REQUEST_TIMEOUT_MS = 60000;

/**
 * 用 Node.js 内置 https 模块发送 JSON POST 请求。
 * @param {string} requestUrl - 完整请求 URL
 * @param {Object} body - 请求体对象
 * @param {Object} headers - 额外请求头（含 Authorization）
 * @param {number} timeoutMs - 超时毫秒
 * @returns {Promise<Object>} { statusCode, data, raw }
 * @throws {Error} 网络/超时抛出含 url 的 Error
 */
function _httpsPost(requestUrl, body, headers, timeoutMs) {
  return new Promise((resolve, reject) => {
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
      hostname: 'api.openai.com',
      path: '/v1/responses',
      headers: finalHeaders,
    };
    // 支持自定义 base（如私有化网关），按 URL 解析 host/path
    try {
      const parsed = new URL(requestUrl);
      options.hostname = parsed.hostname;
      options.path = parsed.pathname + parsed.search;
      options.port = parsed.port || (parsed.protocol === 'https:' ? 443 : 80);
    } catch (e) {
      // requestUrl 非法时回退到默认 host（已设置）
    }
    const req = https.request(options, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const raw = Buffer.concat(chunks).toString('utf8');
        let parsedBody;
        try {
          parsedBody = raw ? JSON.parse(raw) : {};
        } catch (e2) {
          parsedBody = raw;
        }
        resolve({ statusCode: res.statusCode, data: parsedBody, raw: raw });
      });
    });
    req.on('error', (err) => {
      reject(new Error(`llm-client: 网络请求失败 ${err.message}`));
    });
    if (timeoutMs && timeoutMs > 0) {
      req.setTimeout(timeoutMs, () => {
        req.destroy(new Error(`llm-client: 请求超时 (${timeoutMs}ms)`));
      });
    }
    req.write(payload);
    req.end();
  });
}

/**
 * 从 OpenAI Responses API 响应中提取结构化 JSON 文本并解析。
 * 兼容三种返回形态：顶层 output_text / output[].content[].text / output[].content[].output_text。
 * @param {Object} data - Responses API 响应体
 * @returns {Object} 已解析的 JSON 对象
 * @throws {Error} 找不到文本或 JSON 解析失败时抛出含上下文的 Error
 */
function _extractStructuredData(data) {
  let text = '';
  if (data && typeof data === 'object') {
    // 便捷字段
    if (typeof data.output_text === 'string' && data.output_text) {
      text = data.output_text;
    } else if (Array.isArray(data.output)) {
      for (let i = 0; i < data.output.length && !text; i++) {
        const item = data.output[i];
        if (!item || typeof item !== 'object') continue;
        const content = item.content;
        if (Array.isArray(content)) {
          for (let j = 0; j < content.length && !text; j++) {
            const c = content[j];
            if (!c || typeof c !== 'object') continue;
            // 优先 output_text / text 字段
            const t = c.text != null ? c.text : c.output_text;
            if (typeof t === 'string' && t) {
              text = t;
            }
          }
        } else if (typeof item.text === 'string' && item.text) {
          text = item.text;
        }
      }
    }
  }
  if (!text) {
    throw new Error(
      `llm-client: 响应中未找到结构化输出文本 raw=${JSON.stringify(data).slice(0, 500)}`
    );
  }
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error(
      `llm-client: 结构化输出 JSON 解析失败 ${e.message}; text=${String(text).slice(0, 500)}`
    );
  }
}

/**
 * 调用 LLM API 返回结构化 JSON 结果。
 * @param {string|Object} payload - 字符串（作为 input）或 { instructions, input } 对象
 * @param {Object} schema - JSON Schema 对象，约束 LLM 输出结构
 * @param {Object} [options] - 可选参数：{ model, schemaName, temperature, timeoutMs }
 * @returns {Promise<Object>} { data: {...}, usage: { prompt_tokens, completion_tokens, total_tokens } }
 * @throws {Error} API 错误 / 网络错误 / JSON 解析错误
 */
async function completeStructured(payload, schema, options) {
  if (!schema || typeof schema !== 'object') {
    throw new Error('llm-client.completeStructured: schema 参数无效');
  }
  options = options || {};

  // 读取 API Key（必填）与 model（可选，默认 gpt-4o）
  const apiKey = await config.getRequired('LLM_API_KEY');
  let model = options.model;
  if (!model) {
    model = (await config.get('LLM_MODEL')) || DEFAULT_MODEL;
  }

  // 解析 payload 为 instructions + input
  let instructions;
  let input;
  if (typeof payload === 'string') {
    instructions = '你是 WorkBuddy 派单助手，请严格按给定 JSON Schema 输出结构化结果，不要输出多余内容。';
    input = payload;
  } else if (payload && typeof payload === 'object') {
    instructions =
      payload.instructions ||
      '你是 WorkBuddy 派单助手，请严格按给定 JSON Schema 输出结构化结果，不要输出多余内容。';
    input = payload.input || '';
  } else {
    throw new Error('llm-client.completeStructured: payload 参数无效（需为字符串或对象）');
  }

  const schemaName = options.schemaName || 'structured_result';
  const requestBody = {
    model: model,
    instructions: instructions,
    input: input,
    response_format: {
      type: 'json_schema',
      json_schema: {
        name: schemaName,
        strict: true,
        schema: schema,
      },
    },
  };
  if (typeof options.temperature === 'number') {
    requestBody.temperature = options.temperature;
  }
  if (typeof options.max_output_tokens === 'number') {
    requestBody.max_output_tokens = options.max_output_tokens;
  }

  const requestUrl = OPENAI_API_BASE + '/v1/responses';
  const timeoutMs = options.timeoutMs || REQUEST_TIMEOUT_MS;
  let resp;
  try {
    resp = await _httpsPost(
      requestUrl,
      requestBody,
      { Authorization: `Bearer ${apiKey}` },
      timeoutMs
    );
  } catch (err) {
    throw new Error(`llm-client: 调用 LLM 失败 ${err.message}`);
  }

  // HTTP 非 2xx 视为 API 错误
  if (resp.statusCode < 200 || resp.statusCode >= 300) {
    const body = resp.data || {};
    const errMsg =
      (body && typeof body === 'object' && body.error && (body.error.message || body.error)) ||
      (typeof resp.raw === 'string' ? resp.raw : JSON.stringify(resp.raw || {}));
    throw new Error(
      `llm-client: LLM API 错误 HTTP ${resp.statusCode} body=${typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg)}`
    );
  }

  const data = resp.data || {};
  const structured = _extractStructuredData(data);

  // 提取 usage（Responses API 返回 input_tokens/output_tokens/total_tokens）
  const usage = data.usage || {};
  return {
    data: structured,
    usage: {
      prompt_tokens: usage.input_tokens || usage.prompt_tokens || 0,
      completion_tokens: usage.output_tokens || usage.completion_tokens || 0,
      total_tokens: usage.total_tokens || 0,
    },
  };
}

module.exports = {
  completeStructured: completeStructured,
};
