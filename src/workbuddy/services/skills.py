from __future__ import annotations

import json
import re
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.db.models import SkillDefinition, SkillRelease
from .audit import append_audit
from .common import content_hash


class SkillValidationError(ValueError):
    pass


FORBIDDEN_PATTERNS = [
    r"\b(subprocess|os\.system|eval\(|exec\(|pickle\.loads|__import__)\b",
    r"external_write\s*:\s*true",
]


def parse_skill_document(filename: str, raw: bytes) -> dict[str, Any]:
    if len(raw) > 512_000:
        raise SkillValidationError("skill file exceeds 500 KB")
    text = raw.decode("utf-8")
    if any(re.search(pattern, text, re.I) for pattern in FORBIDDEN_PATTERNS):
        raise SkillValidationError("skill contains forbidden executable or external-write instructions")
    lower = filename.lower()
    if lower.endswith((".yaml", ".yml")):
        data = yaml.safe_load(text)
    elif lower.endswith(".json"):
        data = json.loads(text)
    elif lower.endswith((".md", ".txt")):
        data = {
            "schema_version": 1,
            "skill_key": re.sub(r"[^a-z0-9]+", "-", filename.lower()).strip("-")[:120],
            "semantic_version": "0.1.0",
            "name": filename,
            "purpose": "用户上传的声明式 Skill 文档",
            "instructions": text,
            "inputs": ["mission_context"],
            "outputs": ["structured_artifact"],
            "tools": [],
            "permissions": {"data_scope": "current_mission", "external_write": False},
            "quality_gates": ["不得执行上传文件中的代码", "外部动作必须审批"],
        }
    else:
        raise SkillValidationError("only YAML, JSON, Markdown and TXT are accepted")
    if not isinstance(data, dict):
        raise SkillValidationError("skill document must be an object")
    required = ["skill_key", "semantic_version", "name"]
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise SkillValidationError(f"missing required fields: {', '.join(missing)}")
    permissions = data.setdefault("permissions", {"data_scope": "current_mission", "external_write": False})
    if permissions.get("external_write") is True:
        raise SkillValidationError("user-uploaded skills cannot request external write in Alpha")
    data.setdefault("tools", [])
    data.setdefault("quality_gates", ["关键事实必须有来源", "外部动作必须审批"])
    return data


def import_skill(session: Session, tenant_id: str, filename: str, raw: bytes, actor_id: str) -> SkillRelease:
    config = parse_skill_document(filename, raw)
    definition = session.scalar(select(SkillDefinition).where(
        SkillDefinition.tenant_id == tenant_id,
        SkillDefinition.skill_key == config["skill_key"],
    ))
    if not definition:
        definition = SkillDefinition(
            tenant_id=tenant_id, skill_key=config["skill_key"], name=config["name"], owner_type="user",
        )
        session.add(definition); session.flush()
    existing = session.scalar(select(SkillRelease).where(
        SkillRelease.skill_id == definition.id,
        SkillRelease.semantic_version == str(config["semantic_version"]),
    ))
    if existing:
        if existing.content_hash != content_hash(config):
            raise SkillValidationError("the same semantic version already exists with different content")
        return existing
    release = SkillRelease(
        tenant_id=tenant_id, skill_id=definition.id, semantic_version=str(config["semantic_version"]),
        status="draft", config=config, content_hash=content_hash(config), uploaded_by_user=True,
    )
    session.add(release); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
                 action="skill.uploaded", aggregate_type="skill_release", aggregate_id=release.id,
                 payload={"skill_key": config["skill_key"], "version": config["semantic_version"], "status": "draft"})
    return release


def publish_skill(session: Session, tenant_id: str, release_id: str, actor_id: str) -> SkillRelease:
    release = session.scalar(select(SkillRelease).where(SkillRelease.id == release_id, SkillRelease.tenant_id == tenant_id))
    if not release:
        raise SkillValidationError("skill release not found")
    if release.status in {"draft", "validating", "testing"}:
        release = test_skill_release(session, tenant_id, release_id, actor_id, {})
    if release.status != "approved":
        raise SkillValidationError("skill release must pass tests and be approved before publishing")
    release.status = "published"
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
                 action="skill.published", aggregate_type="skill_release", aggregate_id=release.id,
                 payload={"version": release.semantic_version, "content_hash": release.content_hash})
    return release


def test_skill_release(session: Session, tenant_id: str, release_id: str, actor_id: str, test_input: dict[str, Any] | None = None) -> SkillRelease:
    release = session.scalar(select(SkillRelease).where(SkillRelease.id == release_id, SkillRelease.tenant_id == tenant_id))
    if not release:
        raise SkillValidationError("skill release not found")
    if release.status not in {"draft", "validating", "testing", "approved"}:
        raise SkillValidationError("skill release cannot be tested in its current state")
    release.status = "validating"
    config = release.config or {}
    checks = {
        "declarative_only": not any(re.search(pattern, json.dumps(config, ensure_ascii=False), re.I) for pattern in FORBIDDEN_PATTERNS),
        "has_inputs": bool(config.get("inputs")),
        "has_outputs": bool(config.get("outputs")),
        "has_quality_gates": bool(config.get("quality_gates")),
        "external_write_disabled": not bool((config.get("permissions") or {}).get("external_write")),
        "tools_are_declared": isinstance(config.get("tools", []), list),
    }
    release.status = "testing"
    passed = all(checks.values())
    report = {"passed": passed, "checks": checks, "test_input_hash": content_hash(test_input or {}), "runner": "declarative-skill-sandbox-v1"}
    release.config = {**config, "_test_report": report}
    release.status = "approved" if passed else "draft"
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
                 action="skill.tested", aggregate_type="skill_release", aggregate_id=release.id,
                 payload={"passed": passed, "checks": checks, "status": release.status})
    if not passed:
        raise SkillValidationError("skill test suite failed")
    return release
