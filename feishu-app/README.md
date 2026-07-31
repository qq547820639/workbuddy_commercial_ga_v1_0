# WorkBuddy 飞书妙搭全栈应用

飞书原生应用重写项目。把 Python watch_worker 重写为 Node.js 妙搭云函数，实现纯飞书原生、0 命令行操作的邮箱监听+IM通知。

> **背景**：TRAE lark 插件外部凭据模式不支持 `spark:app:*` scope，无法用 lark-cli 自动创建/部署妙搭应用。代码在本地写好，需手动同步到妙搭 Web 控制台发布。

## 目录结构

```
feishu-app/
├── .spark/
│   └── meta.json              # 妙搭应用元信息（app_id 同步后回填）
├── lib/                        # 共享库
│   ├── constants.js            # 常量（卡片模板、退出码、日志级别）
│   ├── config.js               # 配置读写（config 表）
│   ├── db.js                   # 妙搭数据库访问层
│   ├── logger.js               # 运行日志（worker_log 表）
│   ├── feishu-oauth.js         # 飞书自建应用 OAuth token 管理
│   ├── feishu-mail.js          # 飞书邮箱 OpenAPI 客户端
│   └── feishu-im.js            # 飞书 IM OpenAPI 客户端
├── functions/                   # 妙搭云函数
│   ├── poll_once.js             # 核心轮询（被自动触发任务调）
│   ├── get_status.js            # 仪表盘状态查询
│   ├── list_archives.js         # 归档邮件分页列表
│   ├── update_config.js         # 保存配置项
│   ├── control_worker.js        # 启停 worker
│   └── resend_notification.js   # 重发某封邮件通知
├── pages/                       # HTML 控制台
│   ├── components/nav.html      # 共用顶部导航
│   ├── js/api.js                # API 调用封装
│   ├── index.html               # 仪表盘
│   ├── archives.html            # 归档邮件列表
│   ├── config.html              # 配置表单
│   └── control.html             # 控制台（启停/重发）
├── schema.sql                   # 数据库建表 SQL
├── package.json
└── README.md                    # 本文件
```

## 部署指南（手动）

### 第 1 步：创建飞书自建应用（OAuth 载体）

1. 打开 https://open.feishu.cn/app 登录企业管理员
2. 点「创建企业自建应用」→ 应用名 `WorkBuddy` → 描述「飞书邮箱监听+IM通知」
3. 拿到 `App ID` 和 `App Secret`
4. 在「权限管理」申请并审批 scope：
   - `mail:user_mailbox:readonly`（邮箱只读）
   - `mail:user_mailbox.message:send`（邮箱发信）
   - `im:message:create_by_user`（IM 发消息）
   - `base:record:*`（多维表格读写，预留）
5. 在「安全设置」配置 OAuth 重定向 URL（妙搭应用域名，下一步拿到后回填）

### 第 2 步：创建妙搭全栈应用

1. 打开 https://miaoda.feishu.cn 登录
2. 点「创建应用」→ 应用名 `WorkBuddy` → 类型选「全栈应用」
3. 创建后拿到 `app_id`（`app_` 开头），回填到 `.spark/meta.json`
4. 在妙搭应用「环境变量」配置：
   - `FEISHU_APP_ID` = 飞书自建应用 App ID
   - `FEISHU_APP_SECRET` = 飞书自建应用 App Secret
   - `MIAODA_APP_ID` = 妙搭应用 app_id
   - `MIAODA_OPENAPI_KEY` = 妙搭 OpenAPI 密钥（在「OpenAPI」菜单创建）

### 第 3 步：初始化数据库

1. 在妙搭应用「数据库」菜单
2. 执行 `schema.sql` 的全部 SQL（4 张表 + 预填默认值）
3. 验证 4 张表已创建：`mail_archive` / `config` / `worker_status` / `worker_log`

### 第 4 步：上传云函数代码

1. 把 `feishu-app/functions/` 下 6 个 .js 文件上传到妙搭应用的云函数目录
2. 把 `feishu-app/lib/` 下 7 个 .js 文件上传到云函数能 require 的目录
3. 验证云函数能 require lib（在妙搭 WebIDE 里 `require('../lib/db.js')`）
4. 测试 `poll_once` 云函数：手动触发，看日志是否正常

### 第 5 步：上传 HTML 控制台

1. 把 `feishu-app/pages/` 下所有文件上传到妙搭应用的静态资源目录
2. 调整 `pages/js/api.js` 的 `API_BASE` 为妙搭云函数 HTTP 网关实际路径
3. 访问控制台首页验证导航和 4 个 tab 正常

### 第 6 步：配置自动触发任务（替代 watch_worker）

1. 在妙搭应用「自动触发任务」菜单
2. 创建新任务：
   - 触发类型：间隔触发
   - 间隔：60 秒（或按需调整，最小粒度取决于妙搭版本）
   - 动作：调用云函数 `poll_once`
3. 启用任务，观察 `worker_log` 表是否有新记录
4. 记录 `automation_id`，回填到 `config` 表的 `AUTOMATION_ID` 键

### 第 7 步：配置 OAuth 回调

1. 在妙搭应用创建一个云函数 `oauth_callback`（本次代码未包含，需手动创建）
2. 处理飞书 OAuth 回调，保存 `user_access_token` 和 `refresh_token`
3. 把回调 URL 配置到飞书自建应用的「安全设置」

### 第 8 步：发布上线

1. 在妙搭应用点「发布」
2. 在「可见范围」配置为 `tenant`（企业内所有用户可见）
3. 在飞书工作台添加 WorkBuddy 应用入口（管理员配置应用可见性）
4. 业务用户在工作台点图标 → 完成 OAuth 授权 → 使用

## 环境变量

| 变量 | 说明 |
|---|---|
| `FEISHU_APP_ID` | 飞书自建应用 App ID |
| `FEISHU_APP_SECRET` | 飞书自建应用 App Secret |
| `FEISHU_USER_ACCESS_TOKEN` | 用户访问 token（OAuth 回调后写入） |
| `FEISHU_USER_REFRESH_TOKEN` | 刷新 token（OAuth 回调后写入） |
| `FEISHU_TOKEN_EXPIRES_AT` | token 过期时间戳（毫秒） |
| `MIAODA_APP_ID` | 妙搭应用 ID（app_ 开头） |
| `MIAODA_OPENAPI_KEY` | 妙搭 OpenAPI 密钥 |
| `FEISHU_MAIL_API_BASE` | 飞书邮箱 API 基址（默认 `https://open.feishu.cn/open-apis`，需验证） |
| `MIAODA_API_BASE` | 妙搭 API 基址（默认 `https://miaoda.feishu.cn`，需验证） |

## 数据库表

| 表 | 用途 |
|---|---|
| `mail_archive` | 邮件归档（message_id PK / subject / from_name / from_mail / received_at / body_preview / labels / processing_status） |
| `config` | 配置键值对（config_key PK / config_value / updated_at） |
| `worker_status` | Worker 运行状态，单行表（id=1 / is_running / last_poll_at / total_notified / error_count） |
| `worker_log` | 运行日志（id 自增 / log_level / message / created_at） |

## 已知待验证项

代码在本地写好，以下几项需在妙搭环境实际验证后调整：

1. **妙搭云函数入口签名**：`exports.main = async function(event, context)` 是常见模式，具体可能不同
2. **妙搭云函数 HTTP 网关路径**：`pages/js/api.js` 的 `API_BASE` 需按实际网关调整
3. **妙搭数据库 OpenAPI 调用方式**：`lib/db.js` 的 API 路径需验证
4. **飞书邮箱 OpenAPI 路径**：`lib/feishu-mail.js` 的接口路径需验证（可能和 lark-cli 内部路径不同）
5. **妙搭自动触发任务最小粒度**：60s 是否可达需在妙搭控制台确认
6. **OAuth 回调云函数**：本次代码未包含，需手动创建 `oauth_callback` 云函数

## 与旧 Python 方案的对比

| 维度 | Python watch_worker（阶段 1/2） | 妙搭全栈应用（阶段 3） |
|---|---|---|
| 部署 | 用户本机常驻 Python 进程 | 妙搭云端常驻，用户 0 部署 |
| 入口 | 终端命令 | 飞书工作台点应用图标 |
| 授权 | `lark-cli auth login`（命令行） | 飞书 OAuth（点同意按钮） |
| 配置 | 改 `.env` 重启 | 控制台表单点保存 |
| 状态 | 看终端日志 | 控制台仪表盘 |
| 数据 | 多维表格 REST 调用 | 妙搭数据库 SQL |
| 启停 | Ctrl+C | 控制台按钮 |

## 现有飞书资产（保留）

- 通知群：`oc_716f4d911915d3e3d91a053e1a80f4a8`
- 多维表格 Base：`ZYzlbTiYgaqnEasv1tuczqjlnie`
- 邮件归档表：`tblKqL7nYS5zS1fE`

以上资产保留不删，作历史数据只读。
