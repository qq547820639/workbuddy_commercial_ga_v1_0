"""飞书多维表格 Base 一次性初始化脚本。

创建 WorkBuddy 数据层 Base（含 6 张表 + 字段），打印环境变量供用户复制到配置。

链路：
  1. lark-cli base +base-create  建库 + 第一张表（邮件归档），拿到 base_token / table_id
  2. lark-cli base +table-create  对剩余 5 张表逐张建表 + 字段
  3. 打印 BASE_TOKEN / *_TABLE_ID 环境变量

注：所有命令用 --as user（TRAE 插件 strict mode 仅允许 user 身份）。
    base-create / table-create 的 --fields 是字段 JSON 数组，结构与 +field-create 一致。
"""

import json
import os
import subprocess
import sys

import base_schema
import config

# 关闭 lark-cli 的更新 / skills 通知，保证 stdout 是干净 JSON
_QUIET_ENV = {
    "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
    "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
}

BASE_NAME = "WorkBuddy数据层"

# 表 -> 环境变量名 映射（顺序与 ALL_TABLES 一致）
_TABLE_ENV_KEYS = [
    ("MAIL_TABLE", "MAIL_TABLE_ID"),
    ("CONFIG_TABLE", "CONFIG_TABLE_ID"),
    ("WORKER_STATUS_TABLE", "WORKER_STATUS_TABLE_ID"),
    ("WORKER_LOG_TABLE", "WORKER_LOG_TABLE_ID"),
    ("TEAM_TABLE", "TEAM_TABLE_ID"),
    ("AGENT_TABLE", "AGENT_TABLE_ID"),
    ("MISSION_TABLE", "MISSION_TABLE_ID"),
    ("WORK_ITEM_TABLE", "WORK_ITEM_TABLE_ID"),
    ("AGENT_RUN_TABLE", "AGENT_RUN_TABLE_ID"),
]


def _log(msg: str) -> None:
    print(f"[base_init] {msg}", flush=True)


def _resolve_cli() -> str:
    """LARK_CLI_PATH 优先，否则用 config.resolve_lark_cli_path()。"""
    return (
        os.environ.get("LARK_CLI_PATH", "").strip()
        or config.resolve_lark_cli_path()
    )


def _run_lark_cli(argv, cli: str) -> tuple[int, str, str]:
    """运行 lark-cli 子进程，返回 (returncode, stdout, stderr)。"""
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


def _parse_json(stdout: str) -> dict:
    """解析 stdout JSON 信封，失败返回空 dict。"""
    if not stdout:
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {}


def _find_first(obj, candidate_keys: list):
    """递归搜索 dict/list，返回第一个匹配 candidate_keys 中任一 key 的值。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in candidate_keys:
                return v
        for v in obj.values():
            found = _find_first(v, candidate_keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_first(item, candidate_keys)
            if found is not None:
                return found
    return None


def _extract_base_token(data) -> str:
    """从 base-create 响应 data 中提取 base token。"""
    # 优先从 data.base.base_token 提取（+base-create 的标准响应结构）
    if isinstance(data, dict):
        base = data.get("base")
        if isinstance(base, dict) and base.get("base_token"):
            return base["base_token"]
    # 回退到递归搜索
    return _find_first(
        data, ["base_token", "app_token", "baseToken", "appToken", "created_base_token"]
    ) or ""


def _extract_table_id(data) -> str:
    """从建表响应 data 中提取 table_id。"""
    # 优先从 data.table.id / data.table.table_id 提取（+base-create 的标准响应结构）
    if isinstance(data, dict):
        table = data.get("table")
        if isinstance(table, dict):
            tid = table.get("id") or table.get("table_id")
            if tid:
                return tid
    # 回退到递归搜索（+table-create 的响应可能是 data.table_id）
    return _find_first(data, ["table_id", "tableId"]) or ""


def main() -> int:
    cli = _resolve_cli()
    _log(f"lark-cli: {cli}")
    _log(f"开始创建 Base：{BASE_NAME}（共 {len(base_schema.ALL_TABLES)} 张表）")

    first_table = base_schema.MAIL_TABLE
    fields_json = json.dumps(first_table["fields"], ensure_ascii=False)

    # 1. 建库 + 第一张表
    argv = [
        cli,
        "base",
        "+base-create",
        "--name",
        BASE_NAME,
        "--table-name",
        first_table["name"],
        "--fields",
        fields_json,
        "--as",
        "user",
        "--format",
        "json",
    ]
    code, stdout, stderr = _run_lark_cli(argv, cli)
    if code != 0:
        _log(f"base-create 失败 code={code} stderr={stderr or stdout}")
        return 1

    resp = _parse_json(stdout)
    if not resp.get("ok"):
        _log(f"base-create 返回错误：{resp or stderr or stdout}")
        return 1

    data = resp.get("data") or {}
    base_token = _extract_base_token(data)
    mail_table_id = _extract_table_id(data)
    if not base_token or not mail_table_id:
        _log(
            "无法从 base-create 响应中解析 base_token / table_id，原始 data："
            f"{json.dumps(data, ensure_ascii=False)}"
        )
        return 1

    _log(f"Base 创建成功：base_token={base_token}")
    _log(f"  邮件归档 table_id={mail_table_id}")

    # 收集 (env_key, table_id)
    table_ids = {"MAIL_TABLE_ID": mail_table_id}

    # 2. 建剩余 5 张表
    for table, (schema_attr, env_key) in zip(
        base_schema.ALL_TABLES[1:], _TABLE_ENV_KEYS[1:]
    ):
        t_fields_json = json.dumps(table["fields"], ensure_ascii=False)
        t_argv = [
            cli,
            "base",
            "+table-create",
            "--base-token",
            base_token,
            "--name",
            table["name"],
            "--fields",
            t_fields_json,
            "--as",
            "user",
            "--format",
            "json",
        ]
        t_code, t_stdout, t_stderr = _run_lark_cli(t_argv, cli)
        if t_code != 0:
            _log(f"table-create[{table['name']}] 失败 code={t_code} stderr={t_stderr or t_stdout}")
            return 1
        t_resp = _parse_json(t_stdout)
        if not t_resp.get("ok"):
            _log(f"table-create[{table['name']}] 返回错误：{t_resp or t_stderr or t_stdout}")
            return 1
        t_id = _extract_table_id(t_resp.get("data") or {})
        if not t_id:
            _log(
                f"无法从 table-create[{table['name']}] 响应解析 table_id，原始 data："
                f"{json.dumps(t_resp.get('data') or {}, ensure_ascii=False)}"
            )
            return 1
        table_ids[env_key] = t_id
        _log(f"  {table['name']} table_id={t_id}")

    # 3. 预填配置默认值（CONFIG_TABLE）
    config_table_id = table_ids.get("CONFIG_TABLE_ID")
    if config_table_id:
        import base_client
        _log("预填配置默认值…")
        for row in base_schema.DEFAULT_CONFIG_ROWS:
            r = base_client.create_record(
                base_token, config_table_id, row, lark_cli_path=cli
            )
            if r.get("ok"):
                _log(f"  配置 {row['config_key']} = {row['config_value']}")
            else:
                _log(f"  配置 {row['config_key']} 写入失败：{r.get('error', r)}")

    # 4. 预填运行状态单行（WORKER_STATUS_TABLE）
    status_table_id = table_ids.get("WORKER_STATUS_TABLE_ID")
    if status_table_id:
        import base_client
        _log("预填运行状态单行…")
        r = base_client.create_record(
            base_token, status_table_id,
            base_schema.DEFAULT_WORKER_STATUS_ROW,
            lark_cli_path=cli,
        )
        if r.get("ok"):
            _log("  运行状态初始行已写入")
        else:
            _log(f"  运行状态初始行写入失败：{r.get('error', r)}")

    # 5. 打印环境变量
    print()
    print("Base 创建成功！")
    print(f"BASE_TOKEN={base_token}")
    for env_key in [ek for _, ek in _TABLE_ENV_KEYS]:
        print(f"{env_key}={table_ids[env_key]}")
    print()
    print("请将以上环境变量添加到你的配置中。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
