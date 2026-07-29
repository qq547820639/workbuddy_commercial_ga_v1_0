# PostgreSQL schema

The authoritative schema is the SQLAlchemy metadata plus Alembic revisions in `migrations/`.
Run `alembic upgrade head`. Revision `0002_postgres_rls` enables forced row-level security using the transaction-local `app.tenant_id` setting.
