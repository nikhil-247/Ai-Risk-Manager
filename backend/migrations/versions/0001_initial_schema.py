"""Create the original transaction, policy, and audit tables.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("risk_category", sa.String(length=12), nullable=False),
        sa.Column("recommended_action", sa.String(length=40), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("score_type", sa.String(length=40), nullable=False),
        sa.Column("disclaimer", sa.Text(), nullable=False),
        sa.Column("review_status", sa.String(length=24), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cross_border", sa.Boolean(), nullable=False),
        sa.Column("transactions_last_hour", sa.Integer(), nullable=False),
        sa.Column("account_age_days", sa.Integer(), nullable=False),
        sa.Column("hour_of_day", sa.Integer(), nullable=False),
        sa.Column("demo_label", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "risk_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("low_max", sa.Integer(), nullable=False),
        sa.Column("review_max", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("transaction_id", sa.String(length=80), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("risk_policies")
    op.drop_table("transactions")
