"""initial schema

Revision ID: c0acdd965a92
Revises:
Create Date: 2026-09-13 17:13:42.887057

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c0acdd965a92"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create jobs and job_steps."""
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                "expired",
                "deleted",
                name="job_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("aligners", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("seq_count", sa.Integer(), nullable=False),
        sa.Column("total_residues", sa.Integer(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_ip_hash", sa.String(length=64), nullable=False),
        sa.Column("tool_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("concat_order", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_action",
            sa.Enum(
                "delete",
                "cancel",
                name="cancel_action",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(
        "ix_jobs_client_ip_created", "jobs", ["client_ip_hash", "created_at"], unique=False
    )
    op.create_index("ix_jobs_expires", "jobs", ["expires_at"], unique=False)
    op.create_index(
        "ix_jobs_queue",
        "jobs",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index("ix_jobs_status_created", "jobs", ["status", "created_at"], unique=False)
    op.create_table(
        "job_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                "timed_out",
                "cancelled",
                "skipped",
                name="step_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stderr_tail", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_steps_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_steps")),
        sa.UniqueConstraint("job_id", "name", name=op.f("uq_job_steps_job_id")),
    )


def downgrade() -> None:
    """Drop everything."""
    op.drop_table("job_steps")
    op.drop_index("ix_jobs_status_created", table_name="jobs")
    op.drop_index("ix_jobs_queue", table_name="jobs", postgresql_where=sa.text("status = 'queued'"))
    op.drop_index("ix_jobs_expires", table_name="jobs")
    op.drop_index("ix_jobs_client_ip_created", table_name="jobs")
    op.drop_table("jobs")
