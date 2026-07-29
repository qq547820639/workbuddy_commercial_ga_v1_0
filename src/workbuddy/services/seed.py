from __future__ import annotations

import os
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.db.models import (
    AgentProfile, SkillDefinition, SkillRelease, TeamConstitutionVersion,
    TeamDefinition, Tenant, TenantPolicy, ToolDefinition, User, WorkflowVersion,
)
from workbuddy.db.session import SessionLocal, apply_tenant_context, init_db
from workbuddy.settings import settings
from .common import content_hash


ROLE_NAMES = {
    "commercial_director": "商务主理人",
    "account_researcher": "客户与需求研究员",
    "deal_strategist": "交易策略师",
    "proposal_writer": "方案与沟通专家",
    "delivery_director": "交付主理人",
    "risk_analyst": "交付风险分析师",
    "delivery_planner": "恢复计划专家",
    "coordination_specialist": "跨部门协调专家",
    "customer_success_director": "客户成功主理人",
    "service_analyst": "客户影响分析师",
    "resolution_coordinator": "解决方案协调员",
    "customer_communicator": "客户沟通专家",
}


def config_root() -> Path:
    explicit = os.getenv("WORKBUDDY_CONFIG_DIR")
    if explicit:
        return Path(explicit)
    cwd = Path.cwd() / "config"
    if cwd.exists():
        return cwd
    return Path(__file__).resolve().parents[3] / "config"


def _load_yaml_files(folder: Path) -> list[dict]:
    result = []
    for path in sorted(folder.glob("*.yaml")):
        result.append(yaml.safe_load(path.read_text(encoding="utf-8")))
    return result


def ensure_skill(session: Session, tenant_id: str, skill_key: str, version: str = "1.0.0", config: dict | None = None) -> SkillRelease:
    definition = session.scalar(select(SkillDefinition).where(
        SkillDefinition.tenant_id == tenant_id,
        SkillDefinition.skill_key == skill_key,
    ))
    if not definition:
        definition = SkillDefinition(tenant_id=tenant_id, skill_key=skill_key, name=(config or {}).get("name", skill_key.replace("-", " ").title()))
        session.add(definition)
        session.flush()
    release = session.scalar(select(SkillRelease).where(
        SkillRelease.skill_id == definition.id,
        SkillRelease.semantic_version == version,
    ))
    if not release:
        safe_config = config or {
            "schema_version": 1,
            "skill_key": skill_key,
            "semantic_version": version,
            "name": definition.name,
            "purpose": "Internal Alpha placeholder governed skill release.",
            "inputs": ["mission_context"],
            "outputs": ["structured_artifact"],
            "procedure": ["核验授权范围", "完成专业分析", "标注事实、推断和缺失信息", "按验收标准提交成果"],
            "tools": [],
            "permissions": {"data_scope": "current_mission", "external_write": False},
            "quality_gates": ["关键事实必须有来源", "不得自行执行外部写操作"],
        }
        release = SkillRelease(
            tenant_id=tenant_id,
            skill_id=definition.id,
            semantic_version=version,
            status="published",
            config=safe_config,
            content_hash=content_hash(safe_config),
        )
        session.add(release)
        session.flush()
    return release


def seed_all(session: Session, tenant_id: str | None = None) -> dict[str, int]:
    tenant_id = tenant_id or settings.default_tenant_id
    tenant = session.get(Tenant, tenant_id)
    if not tenant:
        tenant = Tenant(id=tenant_id, name="WorkBuddy Demo Company")
        session.add(tenant)
        session.flush()
    apply_tenant_context(session, tenant_id, local=True)
    owner = session.scalar(select(User).where(User.tenant_id == tenant_id, User.email == "owner@workbuddy.local"))
    if not owner:
        session.add(User(tenant_id=tenant_id, email="owner@workbuddy.local", name="真人老板", role="owner"))


    tool_specs = {
        "mail_reader": ("邮箱只读工具", "low", ["read_current_mission_source"]),
        "knowledge_reader": ("知识库只读工具", "low", ["search_authorized_knowledge"]),
        "contacts_reader": ("联系人只读工具", "low", ["lookup_contact"]),
        "calendar_reader": ("日历只读工具", "low", ["find_free_busy"]),
        "crm_reader": ("CRM 只读工具", "medium", ["read_current_customer"]),
        "hash_service": ("内容哈希工具", "low", ["sha256"]),
        "spreadsheet_engine": ("情景计算工具", "medium", ["scenario_table"]),
    }
    for tool_key, (name, risk, capabilities) in tool_specs.items():
        if not session.scalar(select(ToolDefinition).where(ToolDefinition.tenant_id == tenant_id, ToolDefinition.tool_key == tool_key)):
            session.add(ToolDefinition(tenant_id=tenant_id, tool_key=tool_key, name=name, risk_level=risk, capabilities=capabilities))

    if not session.scalar(select(TenantPolicy).where(TenantPolicy.tenant_id == tenant_id, TenantPolicy.policy_key == "external_email")):
        session.add(TenantPolicy(tenant_id=tenant_id, policy_key="external_email", version=1, config={
            "require_owner_approval": True, "allow_bcc": False, "allow_attachments": False,
            "daily_send_limit": settings.daily_send_limit, "mission_send_limit": settings.mission_send_limit,
            "allowed_recipient_domains": list(settings.allowed_recipient_domains),
            "allowed_recipient_addresses": list(settings.allowed_recipient_addresses),
        }))

    root = config_root()
    skill_configs = {c["skill_key"]: c for c in _load_yaml_files(root / "skills")}
    for key, cfg in skill_configs.items():
        ensure_skill(session, tenant_id, key, str(cfg.get("semantic_version", "1.0.0")), cfg)

    team_count = workflow_count = agent_count = 0
    for cfg in _load_yaml_files(root / "teams"):
        team = session.scalar(select(TeamDefinition).where(
            TeamDefinition.tenant_id == tenant_id,
            TeamDefinition.team_key == cfg["team_key"],
        ))
        if not team:
            team = TeamDefinition(tenant_id=tenant_id, team_key=cfg["team_key"], name=cfg["name"])
            session.add(team)
            session.flush()
            team_count += 1
        constitution = session.scalar(select(TeamConstitutionVersion).where(
            TeamConstitutionVersion.team_id == team.id,
            TeamConstitutionVersion.version == int(cfg.get("version", 1)),
        ))
        if not constitution:
            constitution = TeamConstitutionVersion(
                tenant_id=tenant_id, team_id=team.id, version=int(cfg.get("version", 1)),
                status="published", config=cfg, content_hash=content_hash(cfg),
            )
            session.add(constitution)
        roles = {cfg["lead_role"]["key"]}
        for wf in cfg.get("default_workflows", []):
            workflow = session.scalar(select(WorkflowVersion).where(
                WorkflowVersion.team_id == team.id,
                WorkflowVersion.workflow_key == wf["key"],
                WorkflowVersion.version == 1,
            ))
            if not workflow:
                workflow = WorkflowVersion(
                    tenant_id=tenant_id, team_id=team.id, workflow_key=wf["key"],
                    name=wf["name"], version=1, status="published", config=wf,
                    content_hash=content_hash(wf),
                )
                session.add(workflow)
                workflow_count += 1
            for item in wf.get("work_items", []):
                roles.add(item["role"])
                spec = item["skill"]
                skill_key, version = spec.rsplit("@", 1)
                ensure_skill(session, tenant_id, skill_key, version, skill_configs.get(skill_key))
        for role in roles:
            profile = session.scalar(select(AgentProfile).where(AgentProfile.team_id == team.id, AgentProfile.role_key == role))
            if not profile:
                session.add(AgentProfile(
                    tenant_id=tenant_id, team_id=team.id, role_key=role,
                    name=ROLE_NAMES.get(role, role.replace("_", " ").title()),
                    is_lead=role == cfg["lead_role"]["key"],
                    profile={"responsibilities": cfg["lead_role"].get("responsibilities", []) if role == cfg["lead_role"]["key"] else []},
                ))
                agent_count += 1
    from .commercial import ensure_plan_catalog
    ensure_plan_catalog(session, tenant_id)
    session.commit()
    return {"teams_created": team_count, "workflows_created": workflow_count, "agents_created": agent_count, "reference_plans": 3}


def main() -> None:
    init_db()
    with SessionLocal() as session:
        print(seed_all(session))


if __name__ == "__main__":
    main()
