"""Add tenant boundaries and backfill existing records to the demo workspace.

Revision ID: 0003_tenant_isolation
Revises: 0002_users
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0003_tenant_isolation"
down_revision = "0002_users"
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-4000-8000-000000000001"
DEFAULT_TENANT_NAME = "Northstar Payments"

_TABLES = ("users", "transactions", "risk_policies", "audit_events")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    tenants = sa.table(
        "tenants",
        sa.column("id", sa.String(length=36)),
        sa.column("name", sa.String(length=120)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(tenants, [{
        "id": DEFAULT_TENANT_ID,
        "name": DEFAULT_TENANT_NAME,
        "created_at": datetime.now(timezone.utc),
    }])

    # Existing rows stay available but are assigned to the original demo workspace.
    for table_name in _TABLES:
        op.add_column(
            table_name,
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
        )
        op.execute(
            sa.text(f"UPDATE {table_name} SET tenant_id = :tenant_id")
            .bindparams(tenant_id=DEFAULT_TENANT_ID)
        )

    for table_name in _TABLES:
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column(
                "tenant_id",
                existing_type=sa.String(length=36),
                nullable=False,
            )
            batch.create_foreign_key(
                f"fk_{table_name}_tenant_id_tenants",
                "tenants",
                ["tenant_id"],
                ["id"],
            )
            batch.create_index(f"ix_{table_name}_tenant_id", ["tenant_id"])

    with op.batch_alter_table("risk_policies") as batch:
        batch.create_unique_constraint(
            "uq_risk_policies_tenant_id",
            ["tenant_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("risk_policies") as batch:
        batch.drop_constraint("uq_risk_policies_tenant_id", type_="unique")

    for table_name in reversed(_TABLES):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_index(f"ix_{table_name}_tenant_id")
            batch.drop_constraint(
                f"fk_{table_name}_tenant_id_tenants",
                type_="foreignkey",
            )
            batch.drop_column("tenant_id")

    op.drop_table("tenants")
