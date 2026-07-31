"""飞书邮箱监听 + IM 通知 MVP —— 配置模块。

从环境变量读取配置，仅使用标准库，不引入第三方依赖。

环境变量：
  NOTIFY_CHAT_ID          必填，通知目标群聊 chat_id（oc_ 开头）
  WATCH_MAILBOX           可选，+triage / +messages --mailbox 目标邮箱，默认 "me"
  POLL_INTERVAL           可选，REST 轮询间隔（秒），默认 60
  MAX_RECONNECT_BACKOFF   可选，指数退避上限（秒），默认 60
  LARK_CLI_PATH           可选，lark-cli 可执行文件路径，默认走 shutil.which + 插件内置 fallback
  BASE_TOKEN              可选，飞书多维表格 base token（阶段 2 数据持久化，未配则纯内存去重）
  MAIL_TABLE_ID           可选，邮件归档表 table_id（需与 BASE_TOKEN 同时配置）
"""

import os
import shutil
from dataclasses import dataclass

# lark-cli 插件内置二进制的绝对路径，shutil.which 找不到时使用
LARK_CLI_FALLBACK = "/Users/panhao/.trae-cn/plugins/trae-remote-official/lark/1.0.3/bin/lark-cli"


@dataclass
class FeishuConfig:
    """运行配置。"""

    watch_mailbox: str          # +triage / +messages --mailbox 目标邮箱
    notify_chat_id: str         # 通知目标群聊 chat_id（oc_ 开头），必填
    poll_interval: int          # REST 轮询间隔（秒）
    max_reconnect_backoff: int  # 指数退避上限（秒）
    lark_cli_path: str          # lark-cli 可执行文件路径
    base_token: str = ""        # 多维表格 base token（阶段 2 数据持久化，空则纯内存去重）
    mail_table_id: str = ""     # 邮件归档表 table_id（需与 base_token 同时配置）


def resolve_lark_cli_path() -> str:
    """优先用 PATH 中的 lark-cli，找不到则用插件内置绝对路径。"""
    found = shutil.which("lark-cli")
    if found:
        return found
    return LARK_CLI_FALLBACK


def _parse_int(value: str, default: int) -> int:
    """解析正整数，非法或非正时回退默认值。"""
    try:
        n = int(value)
        return n if n > 0 else default
    except (TypeError, ValueError):
        return default


def load_config() -> FeishuConfig:
    """从环境变量加载配置。

    NOTIFY_CHAT_ID 缺失时抛 RuntimeError，提示如何设置。
    """
    notify_chat_id = os.environ.get("NOTIFY_CHAT_ID", "").strip()
    if not notify_chat_id:
        raise RuntimeError(
            "未设置 NOTIFY_CHAT_ID 环境变量。"
            "请先创建一个飞书群（或用已有群）并把机器人拉入，拿到群 chat_id（oc_ 开头）后：\n"
            "  export NOTIFY_CHAT_ID=oc_xxxxxxxxxxxxxxxx"
        )

    return FeishuConfig(
        watch_mailbox=(os.environ.get("WATCH_MAILBOX", "me").strip() or "me"),
        notify_chat_id=notify_chat_id,
        poll_interval=_parse_int(
            os.environ.get("POLL_INTERVAL", "60"), 60
        ),
        max_reconnect_backoff=_parse_int(
            os.environ.get("MAX_RECONNECT_BACKOFF", "60"), 60
        ),
        lark_cli_path=(
            os.environ.get("LARK_CLI_PATH", "").strip() or resolve_lark_cli_path()
        ),
        base_token=os.environ.get("BASE_TOKEN", "").strip(),
        mail_table_id=os.environ.get("MAIL_TABLE_ID", "").strip(),
    )
