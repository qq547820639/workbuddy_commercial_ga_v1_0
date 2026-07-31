"""飞书 IM 通知器：把 +watch 收到的邮件事件构造成交互卡片发到目标群聊。

命令格式（以 lark-im SKILL.md / lark-im-card-create.md Step 4 为准）：
  lark-cli im +messages-send --as user --chat-id <oc_xxx> \\
      --msg-type interactive --content '<card_json>'
  注：TRAE 插件 strict mode 仅允许 user 身份，不能用 --as bot

JSON 契约（参考 lark-shared SKILL.md）：
  - 成功信封在 stdout：{"ok":true,"identity":"...","data":{"message_id":"om_xxx",...}}，退出码 0
  - 错误信封在 stderr：{"ok":false,"error":{"type","subtype","message","hint",...}}，退出码非 0
  - 判断成功必须用 ok == true，不要用 code == 0
"""

import datetime
import json
import os
import shutil
import subprocess

# 关闭 lark-cli 的更新 / skills 通知，保证 stdout 是干净 JSON
_QUIET_ENV = {
    "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
    "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
}

# lark-cli 插件内置二进制 fallback（与 config.py 保持一致）
_LARK_CLI_FALLBACK = "/Users/panhao/.trae-cn/plugins/trae-remote-official/lark/1.0.3/bin/lark-cli"


def _default_lark_cli_path() -> str:
    """优先用 PATH 中的 lark-cli，找不到则用插件内置绝对路径。"""
    found = shutil.which("lark-cli")
    if found:
        return found
    return _LARK_CLI_FALLBACK


def _extract_message(mail_data: dict) -> dict:
    """从一行 NDJSON 解析结果中取出 message dict。

    兼容三种形态：
      - 裸 data：{"message":{...}}              （+watch --format data 的默认输出）
      - json 信封：{"ok":true,"data":{"message":{...}}}
      - 裸 message：{"message_id":...}
    """
    if not isinstance(mail_data, dict):
        return {}
    # json 信封
    if isinstance(mail_data.get("data"), dict):
        mail_data = mail_data["data"]
    # data 包了一层 message，或本身就是裸 message
    msg = mail_data.get("message")
    if isinstance(msg, dict):
        return msg
    return mail_data


def _fmt_time(internal_date) -> str:
    """internal_date 是毫秒级 epoch 字符串，转本地可读时间。"""
    try:
        ms = int(internal_date)
        return datetime.datetime.fromtimestamp(ms / 1000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError, OSError, OverflowError):
        return str(internal_date) if internal_date else "未知"


def _truncate(text, limit: int) -> str:
    """截断文本，超出加省略号。"""
    if not text:
        return ""
    s = str(text)
    return s if len(s) <= limit else s[:limit] + "…"


def build_card(mail_data: dict) -> dict:
    """根据 +watch metadata 模式的一行数据构造 Card 2.0 交互卡片。

    包含 subject / 发件人(name+mail) / 时间 / 正文预览，仅用基础展示组件。
    """
    msg = _extract_message(mail_data)
    subject = msg.get("subject") or "(无主题)"
    head_from = msg.get("head_from") or {}
    from_name = head_from.get("name") or "未知发件人"
    from_mail = head_from.get("mail_address") or ""
    body_preview = _truncate(msg.get("body_preview"), 300)
    time_str = _fmt_time(msg.get("internal_date"))

    from_line = f"**发件人**\n{from_name}"
    if from_mail:
        from_line += f" <{from_mail}>"

    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": from_line}},
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**时间**\n{time_str}"}},
        {"tag": "hr"},
        {
            "tag": "markdown",
            "content": f"**正文预览**\n{body_preview}" if body_preview else "**正文预览**\n(无预览)",
        },
    ]

    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {
            "title": {"tag": "plain_text", "content": "新邮件"},
            "subtitle": {"tag": "plain_text", "content": _truncate(subject, 60)},
            "template": "blue",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "elements": elements,
        },
    }


def send_mail_notification(
    mail_data: dict, chat_id: str, lark_cli_path: str = None
) -> dict:
    """把邮件事件发成 IM 交互卡片到 chat_id。

    参数：
      mail_data:    +watch metadata 模式一行 NDJSON 解析后的 dict
      chat_id:      目标群聊 chat_id（oc_ 开头）
      lark_cli_path:可选，lark-cli 路径，默认自动解析

    返回 lark-cli 的解析结果 dict（成功含 ok:true/data，失败含 ok:false/error）。
    发送失败只打印错误信封，不抛异常，避免拖垮 worker。
    """
    cli = lark_cli_path or _default_lark_cli_path()
    card = build_card(mail_data)
    card_json = json.dumps(card, ensure_ascii=False)

    # 用参数数组传递，避免 shell 转义问题；--content 接收卡片 JSON 字符串
    # --as user：TRAE 插件 strict mode 仅允许 user 身份（bot 身份不可用）
    argv = [
        cli,
        "im",
        "+messages-send",
        "--as",
        "user",
        "--chat-id",
        chat_id,
        "--msg-type",
        "interactive",
        "--content",
        card_json,
    ]

    env = dict(os.environ)
    env.update(_QUIET_ENV)

    try:
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )
    except FileNotFoundError:
        print(f"[notifier] lark-cli 未找到：{cli}", flush=True)
        return {"ok": False, "error": {"message": f"lark-cli not found: {cli}"}}
    except Exception as exc:  # noqa: BLE001 — 兜底，绝不向上抛
        print(f"[notifier] 调用 lark-cli 异常：{exc}", flush=True)
        return {"ok": False, "error": {"message": str(exc)}}

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    result = {}
    if stdout:
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError:
            # 非 JSON 输出，按退出码兜底
            result = {"ok": proc.returncode == 0, "raw": stdout}

    if not result.get("ok"):
        # 错误信封在 stderr；解析出来打印，便于排查
        err = {}
        if stderr:
            try:
                err = json.loads(stderr)
            except json.JSONDecodeError:
                err = {"message": stderr}
        err_brief = err.get("error", err) if err else stderr or stdout
        print(
            f"[notifier] 发送失败 code={proc.returncode} error={err_brief}",
            flush=True,
        )
        if err and not result.get("error"):
            result.setdefault("error", err.get("error", err))
        result.setdefault("ok", False)

    return result


if __name__ == "__main__":
    # 自测：用一行假数据走一遍卡片构造 + 发送（需 NOTIFY_CHAT_ID）
    import sys

    chat = os.environ.get("NOTIFY_CHAT_ID")
    if not chat:
        print("未设置 NOTIFY_CHAT_ID，跳过自测", file=sys.stderr)
        sys.exit(2)
    sample = {
        "message": {
            "message_id": "om_test",
            "thread_id": "om_test",
            "subject": "【自测】飞书邮箱通知 MVP",
            "head_from": {"name": "测试发件人", "mail_address": "tester@example.com"},
            "folder_id": "INBOX",
            "internal_date": str(int(datetime.datetime.now().timestamp() * 1000)),
            "body_preview": "这是一封自测邮件的正文预览，用于验证 notifier 链路。",
        }
    }
    print(json.dumps(build_card(sample), ensure_ascii=False, indent=2))
    resp = send_mail_notification(sample, chat)
    print(json.dumps(resp, ensure_ascii=False))
