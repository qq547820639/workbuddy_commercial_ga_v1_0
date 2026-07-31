"""飞书邮箱监听 + IM 通知 MVP —— 配置模块。

优先从环境变量读取配置；环境变量缺失时，若 BASE_TOKEN + CONFIG_TABLE_ID 已配置，
则从飞书多维表格「配置」表回退读取（小白用户可直接在飞书表格里改配置）。

环境变量：
  NOTIFY_CHAT_ID          必填（或从 Base 配置表读取），通知目标群聊 chat_id（oc_ 开头）
  WATCH_MAILBOX           可选，+triage / +messages --mailbox 目标邮箱，默认 "me"
  POLL_INTERVAL           可选，REST 轮询间隔（秒），默认 60
  MAX_RECONNECT_BACKOFF   可选，指数退避上限（秒），默认 60
  LARK_CLI_PATH           可选，lark-cli 可执行文件路径，默认走 shutil.which + 插件内置 fallback
  BASE_TOKEN              可选，飞书多维表格 base token（数据持久化，未配则纯内存去重）
  MAIL_TABLE_ID           可选，邮件归档表 table_id（需与 BASE_TOKEN 同时配置）
  CONFIG_TABLE_ID         可选，配置表 table_id（启用 Base 配置回退）
  WORKER_STATUS_TABLE_ID  可选，运行状态表 table_id（启用状态写入）
  WORKER_LOG_TABLE_ID     可选，运行日志表 table_id（启用日志写入）
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
    base_token: str = ""                 # 多维表格 base token（空则纯内存去重）
    mail_table_id: str = ""              # 邮件归档表 table_id
    config_table_id: str = ""            # 配置表 table_id（Base 配置回退）
    worker_status_table_id: str = ""     # 运行状态表 table_id（状态写入）
    worker_log_table_id: str = ""        # 运行日志表 table_id（日志写入）


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


def _load_base_config_map(cfg: FeishuConfig) -> dict:
    """从 Base 配置表加载全部配置键值对；失败返回空 dict（不抛异常）。"""
    if not (cfg.base_token and cfg.config_table_id):
        return {}
    try:
        import base_client
        records = base_client.list_records(
            cfg.base_token, cfg.config_table_id,
            max_records=100, lark_cli_path=cfg.lark_cli_path,
        )
        result = {}
        for rec in records:
            fields = rec.get("fields") or {}
            # 配置表字段是 text 类型，可能是字符串或 [{"text":"..."}] 段数组
            key = _cell_text(fields.get("config_key"))
            val = _cell_text(fields.get("config_value"))
            if key:
                result[key] = val
        return result
    except Exception:
        return {}


def _cell_text(value) -> str:
    """从多维表格记录字段值中提取文本（兼容字符串 / 文本段数组）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for seg in value:
            if isinstance(seg, dict):
                parts.append(seg.get("text") or seg.get("name") or "")
            elif seg is not None:
                parts.append(str(seg))
        return "".join(parts)
    return str(value)


def load_config() -> FeishuConfig:
    """加载配置：环境变量优先，Base 配置表回退。

    NOTIFY_CHAT_ID 在环境变量和 Base 配置表都缺失时抛 RuntimeError。
    """
    lark_cli_path = (
        os.environ.get("LARK_CLI_PATH", "").strip() or resolve_lark_cli_path()
    )
    base_token = os.environ.get("BASE_TOKEN", "").strip()
    mail_table_id = os.environ.get("MAIL_TABLE_ID", "").strip()
    config_table_id = os.environ.get("CONFIG_TABLE_ID", "").strip()
    worker_status_table_id = os.environ.get("WORKER_STATUS_TABLE_ID", "").strip()
    worker_log_table_id = os.environ.get("WORKER_LOG_TABLE_ID", "").strip()

    cfg = FeishuConfig(
        watch_mailbox=(os.environ.get("WATCH_MAILBOX", "me").strip() or "me"),
        notify_chat_id=os.environ.get("NOTIFY_CHAT_ID", "").strip(),
        poll_interval=_parse_int(os.environ.get("POLL_INTERVAL", "60"), 60),
        max_reconnect_backoff=_parse_int(
            os.environ.get("MAX_RECONNECT_BACKOFF", "60"), 60
        ),
        lark_cli_path=lark_cli_path,
        base_token=base_token,
        mail_table_id=mail_table_id,
        config_table_id=config_table_id,
        worker_status_table_id=worker_status_table_id,
        worker_log_table_id=worker_log_table_id,
    )

    # 环境变量未配 NOTIFY_CHAT_ID 时，从 Base 配置表回退
    if not cfg.notify_chat_id:
        base_cfg = _load_base_config_map(cfg)
        cfg.notify_chat_id = base_cfg.get("NOTIFY_CHAT_ID", "").strip()
        # Base 配置表可覆盖其他配置项（仅当环境变量未显式设置时）
        if not os.environ.get("POLL_INTERVAL"):
            if "POLL_INTERVAL" in base_cfg:
                cfg.poll_interval = _parse_int(base_cfg["POLL_INTERVAL"], 60)
        if not os.environ.get("MAX_RECONNECT_BACKOFF"):
            if "MAX_RECONNECT_BACKOFF" in base_cfg:
                cfg.max_reconnect_backoff = _parse_int(
                    base_cfg["MAX_RECONNECT_BACKOFF"], 60
                )

    if not cfg.notify_chat_id:
        raise RuntimeError(
            "未设置 NOTIFY_CHAT_ID（环境变量和 Base 配置表均缺失）。"
            "请设置环境变量 NOTIFY_CHAT_ID=oc_xxx，或在飞书多维表格「配置」表中填写 NOTIFY_CHAT_ID。"
        )

    return cfg
