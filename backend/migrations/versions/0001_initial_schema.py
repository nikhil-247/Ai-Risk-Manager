"""Create initial RiskLens AI tables.

Revision ID: 0001_initial
Revises:
"""
from alembic import op

from backend.app.models import AuditEvent, RiskPolicyRecord, TransactionRecord

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().dialect.name  # Ensure the connection is initialized before creating the baseline schema.\n    from backend.app.database import Base\n    Base.metadata.create_all(\n        bind=op.get_bind(),\n        tables=[TransactionRecord.__table__, RiskPolicyRecord.__table__, AuditEvent.__table__],\n    )


def downgrade() -> None:
    from backend.app.database import Base\n    Base.metadata.drop_all(\n        bind=op.get_bind(),\n        tables=[AuditEvent.__table__, RiskPolicyRecord.__table__, TransactionRecord.__table__],\n    )
