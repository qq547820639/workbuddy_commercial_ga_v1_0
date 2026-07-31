#!/bin/bash
# WorkBuddy 一键安装脚本（macOS）
# 双击 .command 文件即可运行：初始化 Base → 保存配置 → 安装 launchd 开机自启 → 启动 worker
set -e

# ===== 颜色 =====
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ===== 定位脚本目录 =====
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

info "WorkBuddy 安装程序"
info "脚本目录: $SCRIPT_DIR"
echo ""

# ===== 1. 检查 Python =====
info "检查 Python 3..."
if command -v python3 &>/dev/null; then
    PYTHON=python3
    ok "Python 3: $(python3 --version)"
else
    err "未找到 python3，请先安装 Python 3"
    exit 1
fi

# ===== 2. 检查 lark-cli =====
info "检查 lark-cli..."
LARK_CLI=""
if command -v lark-cli &>/dev/null; then
    LARK_CLI="$(command -v lark-cli)"
elif [ -f "/Users/panhao/.trae-cn/plugins/trae-remote-official/lark/1.0.3/bin/lark-cli" ]; then
    LARK_CLI="/Users/panhao/.trae-cn/plugins/trae-remote-official/lark/1.0.3/bin/lark-cli"
fi

if [ -z "$LARK_CLI" ]; then
    err "未找到 lark-cli，请先安装 TRAE lark 插件"
    exit 1
fi
ok "lark-cli: $LARK_CLI"

# 检查 auth 状态
info "检查飞书登录状态..."
AUTH_STATUS=$("$LARK_CLI" auth status 2>&1 || true)
if echo "$AUTH_STATUS" | grep -q '"status": "ready"' 2>/dev/null || echo "$AUTH_STATUS" | grep -q "ready" 2>/dev/null; then
    ok "飞书已登录"
else
    warn "飞书登录状态异常，可能需要重新登录"
    echo "  请运行: $LARK_CLI auth login"
    echo ""
    read -p "是否继续安装？(y/N) " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
fi

# ===== 3. 初始化 Base（如果尚未配置） =====
ENV_FILE="$HOME/.workbuddy.env"

if [ -f "$ENV_FILE" ]; then
    info "发现已有配置文件: $ENV_FILE"
    source "$ENV_FILE"
    ok "BASE_TOKEN=${BASE_TOKEN:-未设置}"
else
    info "首次安装：初始化飞书多维表格 Base..."
    echo ""
    echo "即将创建 WorkBuddy 数据层 Base（含配置表/运行状态表/运行日志表/邮件归档表等）"
    echo "这会在你的飞书多维表格中创建一个新的 Base。"
    echo ""
    read -p "是否继续？(Y/n) " -n 1 -r
    echo
    [[ $REPLY =~ ^[Nn]$ ]] && { warn "跳过 Base 初始化"; }

    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        info "运行 base_init.py..."
        LARK_CLI_PATH="$LARK_CLI" $PYTHON base_init.py || {
            err "Base 初始化失败，请检查 lark-cli 登录状态"
            exit 1
        }
        echo ""
        info "请将上方输出的环境变量粘贴到此处（直接回车跳过手动输入）："
        echo "  示例格式: BASE_TOKEN=xxxx MAIL_TABLE_ID=tblxxx ..."
        echo ""
        read -p "粘贴环境变量（或回车跳过）: " ENV_VARS
        if [ -n "$ENV_VARS" ]; then
            echo "$ENV_VARS" > "$ENV_FILE"
            source "$ENV_FILE"
            ok "配置已保存到 $ENV_FILE"
        fi
    fi
fi

# ===== 4. 检查 NOTIFY_CHAT_ID =====
if [ -z "$NOTIFY_CHAT_ID" ]; then
    if [ -n "$BASE_TOKEN" ] && [ -n "$CONFIG_TABLE_ID" ]; then
        ok "NOTIFY_CHAT_ID 将从 Base 配置表读取"
    else
        warn "NOTIFY_CHAT_ID 未设置"
        echo "  请创建一个飞书群，把机器人拉入，拿到群 chat_id（oc_ 开头）"
        read -p "输入 NOTIFY_CHAT_ID（或回车跳过）: " CHAT_ID
        if [ -n "$CHAT_ID" ]; then
            echo "NOTIFY_CHAT_ID=$CHAT_ID" >> "$ENV_FILE"
            NOTIFY_CHAT_ID="$CHAT_ID"
            ok "NOTIFY_CHAT_ID 已保存"
        fi
    fi
fi

# ===== 5. 确保 ENV_FILE 包含 LARK_CLI_PATH =====
if ! grep -q "LARK_CLI_PATH" "$ENV_FILE" 2>/dev/null; then
    echo "LARK_CLI_PATH=$LARK_CLI" >> "$ENV_FILE"
fi

ok "配置完成"
echo ""

# ===== 6. 安装 launchd 开机自启 =====
PLIST_LABEL="com.workbuddy.watch"
PLIST_FILE="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

info "安装 launchd 开机自启..."

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_FILE" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>${SCRIPT_DIR}/watch_worker.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>LARK_CLI_PATH</key>
        <string>${LARK_CLI}</string>
        <key>BASE_TOKEN</key>
        <string>${BASE_TOKEN:-}</string>
        <key>MAIL_TABLE_ID</key>
        <string>${MAIL_TABLE_ID:-}</string>
        <key>CONFIG_TABLE_ID</key>
        <string>${CONFIG_TABLE_ID:-}</string>
        <key>WORKER_STATUS_TABLE_ID</key>
        <string>${WORKER_STATUS_TABLE_ID:-}</string>
        <key>WORKER_LOG_TABLE_ID</key>
        <string>${WORKER_LOG_TABLE_ID:-}</string>
        <key>NOTIFY_CHAT_ID</key>
        <string>${NOTIFY_CHAT_ID:-}</string>
        <key>POLL_INTERVAL</key>
        <string>${POLL_INTERVAL:-60}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${SCRIPT_DIR}/workbuddy.log</string>
    <key>StandardErrorPath</key>
    <string>${SCRIPT_DIR}/workbuddy.log</string>
</dict>
</plist>
PLISTEOF

ok "plist 已写入: $PLIST_FILE"

# 卸载旧的（如果存在）
launchctl unload "$PLIST_FILE" 2>/dev/null || true
# 加载新的
launchctl load "$PLIST_FILE" 2>/dev/null || true
ok "launchd 已加载（开机自启 + 崩溃自动重启）"

echo ""
ok "============================================"
ok "  WorkBuddy 安装完成！"
ok "============================================"
echo ""
info "应用已启动，将在后台持续运行。"
info "日志文件: $SCRIPT_DIR/workbuddy.log"
info ""
info "在飞书多维表格中查看："
info "  - 「配置」表：修改 NOTIFY_CHAT_ID / POLL_INTERVAL"
info "  - 「运行状态」表：查看 is_running / last_poll_at / total_notified"
info "  - 「运行日志」表：查看最近日志"
info "  - 「邮件归档」表：查看已通知的邮件"
info ""
info "管理命令："
info "  停止: launchctl unload \"$PLIST_FILE\""
info "  启动: launchctl load \"$PLIST_FILE\""
info "  查看日志: tail -f $SCRIPT_DIR/workbuddy.log"
echo ""
read -p "按回车键退出..." -r
