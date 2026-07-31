"""飞书邮箱监听 worker：常驻后台，REST 轮询新邮件并转发为 IM 卡片通知。

核心链路（每轮 poll）：
  1. 调 `lark-cli mail +triage --filter '{"folder":"inbox","is_unread":true}' --format data --max 50`
     拉取未读收件箱邮件列表（bare JSON，无 ok/data 信封）。
  2. 过滤掉已通知过的 message_id（notified_ids 集合去重）。
  3. 若有新邮件，批量调 `lark-cli mail +messages --message-ids <ids> --html=false --format json`
     拉取邮件详情（json 信封：{"ok":true,"data":{"messages":[...]}}）。
  4. 对 data.messages 中每封邮件调 notifier.send_mail_notification 发卡片。
  5. 把处理过的 message_id 加入 notified_ids，避免重复通知。
  6. sleep cfg.poll_interval 秒（可被停止信号打断），回到 1。

为什么 REST 轮询而非 WebSocket：TRAE lark 插件外部凭证模式下不向 WebSocket SDK 提供
appSecret，导致 `mail +watch` 报错 7104，故改用 REST 轮询。

退出码语义：
  0  = 正常退出（收到 SIGTERM/SIGINT）
  2  = 启动配置失败
  3  = auth 失败 / token 过期（需人工 relogin）
"""

import datetime
import json
import os
import signal
import subprocess
import sys
import threading

import base_client
import config
import notifier

# 退出码
EXIT_OK = 0       # 正常退出
EXIT_CONFIG = 2   # 配置失败
EXIT_AUTH = 3     # auth 失败 / token 过期

# 关闭 lark-cli 的更新 / skills 通知，保证 stdout 是干净 JSON
_QUIET_ENV = {
    "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
    "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
}


class AuthError(Exception):
    """lark-cli 返回退出码 3（auth 失败 / token 过期），需人工 relogin。"""


def _log(msg: str) -> None:
    print(f"[watch] {msg}", flush=True)


def _run_lark_cli(argv, cfg) -> tuple[int, str, str]:
    """运行 lark-cli 子进程（短生命周期 REST 调用），返回 (returncode, stdout, stderr)。"""
    env = dict(os.environ)
    env.update(_QUIET_ENV)
    proc = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _cell_text(value) -> str:
    """从多维表格记录字段值中提取文本（兼容字符串 / 文本段数组 [{"text":"..."}]）。"""
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


def _fmt_internal_date(internal_date) -> str:
    """internal_date 是毫秒级 epoch，转多维表格 datetime 字段可接受的 'YYYY-MM-DD HH:MM:SS'。"""
    try:
        ms = int(internal_date)
        return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(internal_date) if internal_date else ""


def _build_mail_archive_fields(msg: dict) -> dict:
    """从邮件详情构造邮件归档表记录字段（顶层 field map，不包 fields）。"""
    head_from = msg.get("head_from") or {}
    labels = msg.get("label_ids") or msg.get("labels") or []
    if isinstance(labels, list):
        labels_str = ",".join(str(l) for l in labels if l)
    else:
        labels_str = str(labels)
    return {
        "message_id": msg.get("message_id") or "",
        "subject": msg.get("subject") or "",
        "from_name": head_from.get("name") or "",
        "from_mail": head_from.get("mail_address") or "",
        "received_at": _fmt_internal_date(msg.get("internal_date")),
        "body_preview": (msg.get("body_preview") or "")[:300],
        "labels": labels_str,
        "processing_status": "NOTIFIED",
    }


def _archive_mail(cfg, mail_data: dict) -> None:
    """把邮件归档到多维表格邮件归档表；失败只记日志，不抛异常、不阻塞通知。"""
    try:
        msg = notifier._extract_message(mail_data)
        fields = _build_mail_archive_fields(msg)
        result = base_client.create_record(
            cfg.base_token,
            cfg.mail_table_id,
            fields,
            lark_cli_path=cfg.lark_cli_path,
        )
        if result.get("ok"):
            _log(f"已归档：{msg.get('subject', '?')[:40]}")
        else:
            _log(f"归档失败：{result.get('error', result)}")
    except Exception as exc:  # noqa: BLE001
        _log(f"归档异常（已吞掉）：{exc}")


def _update_worker_status(cfg, **fields) -> None:
    """更新运行状态表（单行表，id=1）；失败只记日志，不抛异常。"""
    if not (cfg.base_token and cfg.worker_status_table_id):
        return
    try:
        result = base_client.create_record(
            cfg.base_token,
            cfg.worker_status_table_id,
            fields,
            lark_cli_path=cfg.lark_cli_path,
        )
        if not result.get("ok"):
            _log(f"运行状态更新失败：{result.get('error', result)}")
    except Exception as exc:  # noqa: BLE001
        _log(f"运行状态更新异常（已吞掉）：{exc}")


def _write_log(cfg, level: str, message: str) -> None:
    """写一条运行日志到 Base 运行日志表；失败只记日志，不抛异常。"""
    if not (cfg.base_token and cfg.worker_log_table_id):
        return
    try:
        result = base_client.create_record(
            cfg.base_token,
            cfg.worker_log_table_id,
            {
                "log_level": level,
                "message": message[:500],
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            lark_cli_path=cfg.lark_cli_path,
        )
        if not result.get("ok"):
            _log(f"日志写入失败：{result.get('error', result)}")
    except Exception as exc:  # noqa: BLE001
        _log(f"日志写入异常（已吞掉）：{exc}")


def _load_worker_status(cfg) -> dict:
    """从 Base 加载运行状态（total_notified / error_count）；失败返回默认值。"""
    defaults = {"total_notified": 0, "error_count": 0}
    if not (cfg.base_token and cfg.worker_status_table_id):
        return defaults
    try:
        records = base_client.list_records(
            cfg.base_token, cfg.worker_status_table_id,
            max_records=1, lark_cli_path=cfg.lark_cli_path,
        )
        if not records:
            return defaults
        fields = records[0].get("fields") or {}
        defaults["total_notified"] = int(_cell_text(fields.get("total_notified")) or 0)
        defaults["error_count"] = int(_cell_text(fields.get("error_count")) or 0)
        return defaults
    except Exception:
        return defaults


def _poll_once(cfg, notified_ids: set) -> int:
    """单次轮询：triage 拉未读列表 → 过滤去重 → messages 拉详情 → 逐封发通知。

    返回本轮成功发送的通知数。
    """
    # 1. triage 拉未读收件箱列表（bare JSON）
    triage_argv = [
        cfg.lark_cli_path,
        "mail",
        "+triage",
        "--filter",
        '{"folder":"inbox","is_unread":true}',
        "--format",
        "data",
        "--max",
        "50",
    ]
    if cfg.watch_mailbox != "me":
        triage_argv += ["--mailbox", cfg.watch_mailbox]

    code, stdout, stderr = _run_lark_cli(triage_argv, cfg)
    if code == EXIT_AUTH:
        raise AuthError()
    if code != 0:
        raise RuntimeError(f"triage 失败 code={code} stderr={stderr or stdout}")

    try:
        triage_resp = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"triage JSON 解析失败：{exc}；原文={stdout[:200]}") from exc

    messages = triage_resp.get("messages") or []
    new_ids = [
        m.get("message_id")
        for m in messages
        if isinstance(m, dict) and m.get("message_id")
    ]
    # 过滤掉已通知过的 id
    new_ids = [mid for mid in new_ids if mid not in notified_ids]
    _log(f"triage: {len(messages)} unread, {len(new_ids)} new (notified_total={len(notified_ids)})")
    if not new_ids:
        return 0

    # 2. 批量拉邮件详情（json 信封）
    msg_argv = [
        cfg.lark_cli_path,
        "mail",
        "+messages",
        "--message-ids",
        ",".join(new_ids),
        "--html=false",
        "--format",
        "json",
    ]
    if cfg.watch_mailbox != "me":
        msg_argv += ["--mailbox", cfg.watch_mailbox]

    msg_code, msg_stdout, msg_stderr = _run_lark_cli(msg_argv, cfg)
    if msg_code == EXIT_AUTH:
        raise AuthError()

    detailed = []
    if msg_code == 0 and msg_stdout:
        try:
            msg_resp = json.loads(msg_stdout)
            data = msg_resp.get("data") or {}
            detailed = data.get("messages") or []
        except json.JSONDecodeError as exc:
            _log(f"messages JSON 解析失败：{exc}；原文={msg_stdout[:200]}")
    else:
        _log(f"messages 拉取失败 code={msg_code} stderr={msg_stderr or msg_stdout}")

    # 3. 逐封发通知；notifier 内部已吞异常，返回 ok 状态
    _log(f"发送 {len(detailed)} 封邮件通知…")
    notified_count = 0
    for msg in detailed:
        try:
            result = notifier.send_mail_notification(
                msg, cfg.notify_chat_id, lark_cli_path=cfg.lark_cli_path
            )
            if result.get("ok"):
                _log(f"已通知：{msg.get('subject', '?')[:40]}")
                notified_count += 1
            else:
                _log(f"通知发送失败：{result.get('error', result)}")
        except Exception as exc:  # noqa: BLE001
            _log(f"通知发送异常（已吞掉）：{exc}")

        # 通知后归档到多维表格（仅当 base 已配置）；失败只记日志，不阻塞通知
        if cfg.base_token and cfg.mail_table_id:
            _archive_mail(cfg, msg)

    # 4. 全部处理过的 id 入集（即使详情拉取失败也加入，避免反复重试）
    notified_ids.update(new_ids)
    return notified_count


def main() -> int:
    try:
        cfg = config.load_config()
    except RuntimeError as exc:
        print(f"[watch] 启动失败：{exc}", file=sys.stderr, flush=True)
        return 2

    _log(f"lark-cli: {cfg.lark_cli_path}")
    _log(f"mailbox={cfg.watch_mailbox} poll_interval={cfg.poll_interval}s")
    _log(f"通知目标 chat_id={cfg.notify_chat_id}")

    # 从 Base 加载累计计数（跨重启持久化）
    status = _load_worker_status(cfg)
    total_notified = status["total_notified"]
    error_count = status["error_count"]
    _log(f"累计通知={total_notified} 错误次数={error_count}")

    # 标记运行中
    _update_worker_status(cfg, is_running=True)
    _write_log(cfg, "INFO", f"worker 启动 (poll_interval={cfg.poll_interval}s)")

    stop_flag = threading.Event()

    def _handle_signal(signum, _frame):
        _log(f"收到信号 {signum}，停止轮询…")
        stop_flag.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    notified_ids = set()
    # 启动时从 Base 加载已归档邮件 message_id，避免重启后重复通知
    if cfg.base_token and cfg.mail_table_id:
        try:
            records = base_client.list_records(
                cfg.base_token,
                cfg.mail_table_id,
                max_records=100,
                lark_cli_path=cfg.lark_cli_path,
            )
            for rec in records:
                mid = _cell_text((rec.get("fields") or {}).get("message_id"))
                if mid:
                    notified_ids.add(mid)
            _log(f"从 Base 加载 {len(notified_ids)} 条已归档邮件 message_id 用于去重")
        except Exception as exc:  # noqa: BLE001
            _log(f"加载 Base 已归档记录失败（改用纯内存去重）：{exc}")
    else:
        _log("Base 未配置，使用纯内存去重")
    attempt = 0

    while not stop_flag.is_set():
        try:
            notified = _poll_once(cfg, notified_ids)
            total_notified += notified
            attempt = 0
            _update_worker_status(
                cfg,
                is_running=True,
                last_poll_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                total_notified=total_notified,
                error_count=error_count,
            )
        except AuthError:
            _log("token 过期，请重新运行 `lark-cli auth login --domain mail`")
            _write_log(cfg, "ERROR", "token 过期，worker 退出")
            _update_worker_status(cfg, is_running=False)
            return EXIT_AUTH
        except Exception as exc:  # noqa: BLE001
            _log(f"轮询异常：{exc}")
            error_count += 1
            _write_log(cfg, "ERROR", f"轮询异常：{exc}")
            _update_worker_status(cfg, error_count=error_count)
            backoff = min(2 ** attempt, cfg.max_reconnect_backoff)
            _log(f"{backoff}s 后重试")
            attempt += 1

        if stop_flag.wait(timeout=cfg.poll_interval):
            break

    _update_worker_status(cfg, is_running=False)
    _write_log(cfg, "INFO", "worker 退出")
    _log("worker 退出")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
