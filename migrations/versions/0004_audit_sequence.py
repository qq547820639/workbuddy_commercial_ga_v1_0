"""add tenant-local monotonic audit sequence and rebuild chain"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
import hashlib, json
from datetime import timezone
revision="0004_audit_sequence"
down_revision="0003_domain_invariants"
branch_labels=None
depends_on=None

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)

def upgrade():
    bind=op.get_bind(); cols={c['name'] for c in inspect(bind).get_columns('audit_events')}
    if 'sequence' not in cols:
        with op.batch_alter_table('audit_events') as batch:
            batch.add_column(sa.Column('sequence',sa.Integer(),nullable=True))
    rows=bind.execute(sa.text('SELECT id, tenant_id, actor_type, actor_id, action, aggregate_type, aggregate_id, aggregate_version, correlation_id, causation_id, occurred_at, payload FROM audit_events ORDER BY tenant_id, occurred_at, id')).mappings().all()
    counters={}; previous={}
    for row in rows:
        tenant=row['tenant_id']; counters[tenant]=counters.get(tenant,0)+1; seq=counters[tenant]; prev=previous.get(tenant,'0'*64)
        occurred=row['occurred_at']
        if hasattr(occurred,'tzinfo'):
            if occurred.tzinfo is None: occurred=occurred.replace(tzinfo=timezone.utc)
            occurred=occurred.isoformat()
        payload=row['payload']; payload=json.loads(payload) if isinstance(payload,str) else (payload or {})
        core={"id":row['id'],"tenant_id":tenant,"sequence":seq,"actor_type":row['actor_type'],"actor_id":row['actor_id'],"action":row['action'],"aggregate_type":row['aggregate_type'],"aggregate_id":row['aggregate_id'],"aggregate_version":row['aggregate_version'],"correlation_id":row['correlation_id'],"causation_id":row['causation_id'],"occurred_at":occurred,"payload":payload,"previous_hash":prev}
        event_hash=hashlib.sha256(canonical({"previous_hash":prev,"event":core}).encode()).hexdigest()
        bind.execute(sa.text('UPDATE audit_events SET sequence=:seq, previous_hash=:prev, event_hash=:eh WHERE id=:id'),{'seq':seq,'prev':prev,'eh':event_hash,'id':row['id']});previous[tenant]=event_hash
    with op.batch_alter_table('audit_events') as batch:
        batch.alter_column('sequence',nullable=False)
    existing={x['name'] for x in inspect(bind).get_unique_constraints('audit_events')}
    if 'uq_audit_tenant_sequence' not in existing:
        with op.batch_alter_table('audit_events') as batch:
            batch.create_unique_constraint('uq_audit_tenant_sequence',['tenant_id','sequence'])

def downgrade():
    bind=op.get_bind(); cols={c['name'] for c in inspect(bind).get_columns('audit_events')}
    if 'sequence' in cols:
        existing={x['name'] for x in inspect(bind).get_unique_constraints('audit_events')}
        with op.batch_alter_table('audit_events') as batch:
            if 'uq_audit_tenant_sequence' in existing: batch.drop_constraint('uq_audit_tenant_sequence',type_='unique')
            batch.drop_column('sequence')
