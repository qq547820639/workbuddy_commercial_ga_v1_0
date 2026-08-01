'use strict';

/**
 * WorkBuddy 控制台 API 封装。
 *
 * 妙搭云函数 HTTP 调用约定（需在妙搭环境验证）：
 *   - GET  /api/<function_name>?query=params
 *   - POST /api/<function_name>   body 为 JSON
 *
 * 妙搭运行时实际 URL 形态可能不同（如 /function/<name> 或 /<app_id>/<name>），
 * 部署后请按实际网关路径调整下方 API_BASE。
 *
 * 云函数统一返回 { ok: boolean, data?: ..., error?: string }，
 * 本封装在 ok===true 时 resolve(data)，否则 reject(Error(error))。
 */
(function (global) {
  // 云函数基础路径，部署到妙搭后按实际网关路径调整
  var API_BASE = '/api';

  /**
   * 构造 query string，跳过 null/undefined/空字符串。
   */
  function _buildQuery(query) {
    if (!query) return '';
    var parts = Object.keys(query)
      .filter(function (k) {
        var v = query[k];
        return v !== null && v !== undefined && v !== '';
      })
      .map(function (k) {
        return encodeURIComponent(k) + '=' + encodeURIComponent(query[k]);
      });
    return parts.length ? '?' + parts.join('&') : '';
  }

  /**
   * 内部调用云函数。
   * @param {string} name - 云函数名
   * @param {Object} [options] - { method, query, body }
   * @returns {Promise<Object>} resolve(data) / reject(Error)
   */
  function _call(name, options) {
    options = options || {};
    var method = options.method || 'GET';
    var url = API_BASE + '/' + name + (method === 'GET' ? _buildQuery(options.query) : '');
    var fetchOpts = {
      method: method,
      headers: { Accept: 'application/json' }
    };
    if (method !== 'GET' && method !== 'HEAD') {
      fetchOpts.headers['Content-Type'] = 'application/json';
      fetchOpts.body = JSON.stringify(options.body || {});
    }

    return fetch(url, fetchOpts).then(function (resp) {
      var isJson = resp.headers.get('content-type') || '';
      if (isJson.indexOf('application/json') === -1 && resp.status === 404) {
        throw new Error('云函数 ' + name + ' 未找到（HTTP 404），请检查 API_BASE 配置或云函数部署状态');
      }
      return resp.json().then(
        function (json) {
          if (!resp.ok || !json || json.ok === false) {
            var msg = json && json.error ? json.error : 'HTTP ' + resp.status;
            throw new Error(msg);
          }
          return json.data;
        },
        function () {
          throw new Error('云函数 ' + name + ' 返回非 JSON（HTTP ' + resp.status + '）');
        }
      );
    });
  }

  var api = {
    /**
     * 查询仪表盘状态。
     * @returns {Promise<Object>} { is_running, last_poll_at, total_notified, error_count, archive_total, recent_logs[] }
     */
    getStatus: function () {
      return _call('get_status');
    },

    /**
     * 分页查询归档邮件。
     * @param {number} page - 页码，从 1 开始
     * @param {number} size - 每页条数
     * @param {string} [keyword] - 主题模糊搜索
     * @returns {Promise<Object>} { page, size, total, items[] }
     */
    listArchives: function (page, size, keyword) {
      return _call('list_archives', {
        method: 'GET',
        query: { page: page, size: size, keyword: keyword }
      });
    },

    /**
     * 保存单个配置项。
     * @param {string} key - 配置键名
     * @param {string} value - 配置值
     * @returns {Promise<Object>} { config_key, config_value }
     */
    updateConfig: function (key, value) {
      return _call('update_config', {
        method: 'POST',
        body: { config_key: key, config_value: value }
      });
    },

    /**
     * 查询全部配置项。
     * @returns {Promise<Object>} { configs: [{ config_key, config_value, updated_at }] }
     */
    getConfig: function () {
      return _call('get_config');
    },

    /**
     * 分页查询运行日志。
     * @param {number} page - 页码，从 1 开始
     * @param {number} size - 每页条数
     * @param {string} [level] - 日志级别过滤（INFO/WARN/ERROR/DEBUG）
     * @returns {Promise<Object>} { logs: [], total, page, size }
     */
    getLogs: function (page, size, level) {
      return _call('get_logs', {
        method: 'GET',
        query: { page: page, size: size, level: level }
      });
    },

    /**
     * 分页查询归档邮件（支持 subject / from_name / from_mail 搜索）。
     * @param {number} page - 页码，从 1 开始
     * @param {number} size - 每页条数
     * @param {string} [keyword] - 模糊搜索关键词
     * @returns {Promise<Object>} { archives: [], total, page, size }
     */
    getArchives: function (page, size, keyword) {
      return _call('get_archives', {
        method: 'GET',
        query: { page: page, size: size, keyword: keyword }
      });
    },

    /**
     * 启停 worker。
     * @param {string} action - "start" 或 "stop"
     * @returns {Promise<Object>} { is_running, action }
     */
    controlWorker: function (action) {
      return _call('control_worker', {
        method: 'POST',
        body: { action: action }
      });
    },

    /**
     * 按 message_id 重发通知。
     * @param {string} messageId - 邮件 message_id
     * @returns {Promise<Object>} { message_id, subject }
     */
    resendNotification: function (messageId) {
      return _call('resend_notification', {
        method: 'POST',
        body: { message_id: messageId }
      });
    }
  };

  global.WorkBuddyAPI = api;

  /**
   * 共用顶部导航加载器。
   *
   * 用法：页面放 <div id="nav" data-active="dashboard"></div>，
   * 然后 WorkBuddyNav.mount('nav')。
   * 通过 fetch('components/nav.html') 拉取 <template>，克隆 content，
   * 按 data-active 高亮当前 tab，注入容器。<style> 随 content 生效。
   * fetch 失败时降级渲染最小化导航，保证页面可用。
   */
  var NAV_URL = 'components/nav.html';
  function mountNav(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return Promise.reject(new Error('nav 容器不存在: #' + containerId));
    var active = container.getAttribute('data-active') || '';

    return fetch(NAV_URL, { cache: 'no-cache' })
      .then(function (resp) {
        if (!resp.ok) throw new Error('加载导航失败: HTTP ' + resp.status);
        return resp.text();
      })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var template = doc.getElementById('wb-nav-template');
        if (!template) throw new Error('导航模板未找到 (#wb-nav-template)');
        var content = template.content.cloneNode(true);
        if (active) {
          var link = content.querySelector('[data-tab="' + active + '"]');
          if (link) link.classList.add('wb-nav-active');
        }
        container.innerHTML = '';
        container.appendChild(content);
      })
      .catch(function (err) {
        container.innerHTML =
          '<nav style="display:flex;gap:16px;padding:12px 16px;background:#fff;border-bottom:1px solid #e5e6eb;align-items:center;flex-wrap:wrap;">' +
          '<strong style="margin-right:8px;">🤖 WorkBuddy</strong>' +
          '<a href="index.html" style="color:#3370ff;">看板</a>' +
          '<a href="control.html" style="color:#4e5969;">工作区</a>' +
          '<a href="config.html" style="color:#4e5969;">配置</a>' +
          '<a href="logs.html" style="color:#4e5969;">日志</a>' +
          '<a href="archives.html" style="color:#4e5969;">归档</a>' +
          '</nav>';
        console.warn('[WorkBuddyNav] 导航加载失败，使用降级导航:', err && err.message);
      });
  }
  global.WorkBuddyNav = { mount: mountNav };
})(window);
