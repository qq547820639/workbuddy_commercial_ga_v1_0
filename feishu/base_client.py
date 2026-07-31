"""飞书多维表格数据访问层：包装 lark-cli base 命令。

提供记录的创建 / 列表 / 按字段查询能力，供 watch_worker 归档邮件与启动去重使用。
所有方法均不抛异常 —— 失败时 create_record 返回 {"ok": false, "error": ...}，
list_records / find_by_field 返回空列表 []，避免拖垮 worker。

命令契约（参考 lark-shared SKILL.md / base 命令 --help）：
  lark-cli base +record-upsert --base-token <t> --table-id <id> --json '<field_map>' --as user --format json
  lark-cli base +record-list   --base-token <t> --table-id <id> --limit 100 --format json
  lark-cli base +record-list   --base-token <t> --table-id <id> --filter-json '<filter>' --format json

JSON 输出：
  - 成功信封在 stdout：{"ok":true,"data":{"items":[{"record_id":"rec...","fields":{...}},...]}}
  - 错误信封在 stderr：{"ok":false,"error":{...}}，退出码非 0
  - +record-upsert 的 --json 是顶层字段 map，不要包 fields
"""

import json
import os
import shutil
import subprocess

# 关闭 lark-cli 的更新 / skills 通知，保证 stdout 是干净 JSON
_QUIET_ENV = {
    "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
    "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
}

# lark-cli 插件内置二进制 fallback（与 config.py / notifier.py 保持一致）
_LARK_CLI_FALLBACK = "/Users/panhao/.trae-cn/plugins/trae-remote-official/lark/1.0.3/bin/lark-cli"


def _default_lark_cli_path() -> str:
    """优先用 PATH 中的 lark-cli，找不到则用插件内置绝对路径。"""
    found = shutil.which("lark-cli")
    if found:
        return found
    return _LARK_CLI_FALLBACK


def _run_lark_cli(argv, lark_cli_path) -> tuple[int, str, str]:
    """运行 lark-cli 子进程（短生命周期 REST 调用），返回 (returncode, stdout, stderr)。"""
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
        return 127, "", f"lark-cli not found: {lark_cli_path}"
    except Exception as exc:  # noqa: BLE001 — 兜底，绝不向上抛
        return 1, "", str(exc)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _parse_envelope(stdout: str, stderr: str, returncode: int) -> dict:
    """解析 lark-cli JSON 信封，返回 dict。

    优先解析 stdout；stdout 非 JSON 时按退出码兜底；失败时尝试合并 stderr 错误信封。
    """
    result = {}
    if stdout:
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError:
            result = {"ok": returncode == 0, "raw": stdout}
    if not result.get("ok"):
        err = {}
        if stderr:
            try:
                err = json.loads(stderr)
            except json.JSONDecodeError:
                err = {"message": stderr}
        if err and not result.get("error"):
            result.setdefault("error", err.get("error", err))
        result.setdefault("ok", False)
    return result


def _extract_records(data) -> list:
    """从 +record-list / +record-get 响应 data 中提取记录列表。

    实际响应是列式 tabular 结构：
      {
        "data": [[v1, v2, ...], ...],      # 每行单元格值数组
        "fields": ["field_name", ...],     # 字段名数组（与行值平行）
        "record_id_list": ["rec...", ...], # 记录 ID 数组（与行平行）
        "has_more": bool
      }
    每行 zip(fields, row) 转成 {"record_id": ..., "fields": {...}} 形态。
    回退兼容旧的 items / records / 裸 dict 数组形态。
    """
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if not isinstance(data, dict):
        return []

    # 优先处理 tabular 列式格式（+record-list / +record-get 的标准返回）
    rows = data.get("data")
    field_names = data.get("fields")
    record_ids = data.get("record_id_list")
    if (
        isinstance(rows, list)
        and isinstance(field_names, list)
        and field_names
    ):
        records = []
        for i, row in enumerate(rows):
            if not isinstance(row, list):
                continue
            fields_map = dict(zip(field_names, row))
            rec = {"fields": fields_map}
            if isinstance(record_ids, list) and i < len(record_ids):
                rec["record_id"] = record_ids[i]
            records.append(rec)
        return records

    # 回退：兼容 items / records / rows / 裸 dict 数组形态
    for key in ("items", "records", "rows"):
        val = data.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
    # 最后兜底：data 是 list of dict（避免再误命中 tabular 的 data 键）
    val = data.get("data")
    if isinstance(val, list):
        return [r for r in val if isinstance(r, dict)]
    return []


def create_record(base_token: str, table_id: str, fields: dict, lark_cli_path=None) -> dict:
    """创建/更新一条记录（+record-upsert）。

    参数：
      base_token:    多维表格 base token
      table_id:      表 ID（tbl 开头）或表名
      fields:        字段 map，如 {"message_id":"abc","subject":"test"}；
                     不要包一层 fields，直接传顶层字段 map
      lark_cli_path: 可选，lark-cli 路径，默认自动解析

    返回 lark-cli 解析结果 dict（成功含 ok:true/data，失败含 ok:false/error）。
    """
    cli = lark_cli_path or _default_lark_cli_path()
    payload = json.dumps(fields, ensure_ascii=False)
    argv = [
        cli,
        "base",
        "+record-upsert",
        "--base-token",
        base_token,
        "--table-id",
        table_id,
        "--json",
        payload,
        "--as",
        "user",
        "--format",
        "json",
    ]

    code, stdout, stderr = _run_lark_cli(argv, cli)
    if code == 127:
        print(f"[base_client] lark-cli 未找到：{cli}", flush=True)
        return {"ok": False, "error": {"message": f"lark-cli not found: {cli}"}}
    return _parse_envelope(stdout, stderr, code)


def list_records(base_token: str, table_id: str, max_records: int = 100, lark_cli_path=None) -> list:
    """列出表内记录（+record-list）。

    参数：
      base_token:    多维表格 base token
      table_id:      表 ID（tbl 开头）或表名
      max_records:   最多返回条数（透传给 --limit，范围 1-200）
      lark_cli_path: 可选，lark-cli 路径，默认自动解析

    返回记录列表（每项形如 {"record_id":"rec...","fields":{...}}）；失败返回 []。
    """
    cli = lark_cli_path or _default_lark_cli_path()
    # limit 范围 1-200，越界钳到合法区间
    limit = max(1, min(int(max_records), 200))
    argv = [
        cli,
        "base",
        "+record-list",
        "--base-token",
        base_token,
        "--table-id",
        table_id,
        "--limit",
        str(limit),
        "--as",
        "user",
        "--format",
        "json",
    ]

    code, stdout, stderr = _run_lark_cli(argv, cli)
    if code == 127:
        print(f"[base_client] lark-cli 未找到：{cli}", flush=True)
        return []
    result = _parse_envelope(stdout, stderr, code)
    if not result.get("ok"):
        err_brief = result.get("error", stderr or stdout)
        print(f"[base_client] list_records 失败 code={code} error={err_brief}", flush=True)
        return []
    data = result.get("data") or {}
    return _extract_records(data)


def find_one_by_field(
    base_token: str,
    table_id: str,
    field_name: str,
    field_value,
    lark_cli_path=None,
) -> dict:
    """按字段精确相等查询单条记录，返回 {"record_id":..., "fields":{...}} 或 {}。"""
    records = find_by_field(base_token, table_id, field_name, field_value, lark_cli_path)
    return records[0] if records else {}


def list_all_records(base_token: str, table_id: str, lark_cli_path=None) -> list:
    """列出表内全部记录（分页拉取，自动翻页）。"""
    cli = lark_cli_path or _default_lark_cli_path()
    all_records = []
    page_size = 200
    offset = 0
    while True:
        records = list_records(base_token, table_id, max_records=page_size, lark_cli_path=cli)
        if not records:
            break
        all_records.extend(records)
        if len(records) < page_size:
            break
        offset += page_size
    return all_records


def find_by_field(
    base_token: str,
    table_id: str,
    field_name: str,
    field_value,
    lark_cli_path=None,
) -> list:
    """按字段精确相等查询记录（+record-list --filter-json）。

    参数：
      base_token:    多维表格 base token
      table_id:      表 ID（tbl 开头）或表名
      field_name:    字段名
      field_value:   字段值（字符串/数字）
      lark_cli_path: 可选，lark-cli 路径，默认自动解析

    返回匹配记录列表；失败返回 []。
    """
    cli = lark_cli_path or _default_lark_cli_path()
    filter_obj = {
        "logic": "and",
        "conditions": [[field_name, "==", field_value]],
    }
    argv = [
        cli,
        "base",
        "+record-list",
        "--base-token",
        base_token,
        "--table-id",
        table_id,
        "--filter-json",
        json.dumps(filter_obj, ensure_ascii=False),
        "--limit",
        "100",
        "--as",
        "user",
        "--format",
        "json",
    ]

    code, stdout, stderr = _run_lark_cli(argv, cli)
    if code == 127:
        print(f"[base_client] lark-cli 未找到：{cli}", flush=True)
        return []
    result = _parse_envelope(stdout, stderr, code)
    if not result.get("ok"):
        err_brief = result.get("error", stderr or stdout)
        print(
            f"[base_client] find_by_field 失败 code={code} error={err_brief}",
            flush=True,
        )
        return []
    data = result.get("data") or {}
    return _extract_records(data)
