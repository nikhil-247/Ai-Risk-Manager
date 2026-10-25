"""Create initial RiskLens AI tables.

Revision ID: 0001_initial
Revises:
"""
from alembic import op

from backend.app.database import Base
from backend.app.models import AuditEvent, RiskPolicyRecord, TransactionRecord

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

_LEGACY_TABLES = [
    TransactionRecord.__table__,
    RiskPolicyRecord.__table__,
    AuditEvent.__table__,
]


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=_LEGACY_TABLES)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=list(reversed(_LEGACY_TABLES)))
