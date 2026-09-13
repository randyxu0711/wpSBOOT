import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from wpsboot.pipeline import StepStatus


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"
    DELETED = "deleted"


class CancelAction(StrEnum):
    DELETE = "delete"  # stop, remove files, hide the job
    CANCEL = "cancel"  # stop and mark failed (admin)


FINISHED_STATUSES = (JobStatus.SUCCEEDED, JobStatus.FAILED)


def _enum(enum: type[StrEnum], name: str) -> Enum:
    # Stored as VARCHAR + CHECK constraint (easier to migrate than native PG enums).
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda e: [m.value for m in e],
    )


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {  # noqa: RUF012
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[str]: JSONB,
    }


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.QUEUED
    )
    aligners: Mapped[list[str]] = mapped_column(ARRAY(String(32)))
    seq_count: Mapped[int]
    total_residues: Mapped[int]
    warnings: Mapped[list[str]] = mapped_column(default=list)
    email: Mapped[str | None] = mapped_column(String(320))
    notified_at: Mapped[datetime | None]
    client_ip_hash: Mapped[str] = mapped_column(String(64))
    tool_versions: Mapped[dict[str, Any] | None]
    concat_order: Mapped[list[str] | None]
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(default=0)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    heartbeat_at: Mapped[datetime | None]
    cancel_requested_at: Mapped[datetime | None]
    cancel_action: Mapped[CancelAction | None] = mapped_column(_enum(CancelAction, "cancel_action"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    expires_at: Mapped[datetime]

    steps: Mapped[list["JobStep"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobStep.id",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_jobs_queue", "created_at", postgresql_where=text("status = 'queued'")),
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_client_ip_created", "client_ip_hash", "created_at"),
        Index("ix_jobs_expires", "expires_at"),
    )

    def step(self, name: str) -> "JobStep":
        return next(s for s in self.steps if s.name == name)


class JobStep(Base):
    __tablename__ = "job_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(32))
    status: Mapped[StepStatus] = mapped_column(
        _enum(StepStatus, "step_status"), default=StepStatus.PENDING
    )
    exit_code: Mapped[int | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    stderr_tail: Mapped[str | None] = mapped_column(Text)

    job: Mapped[Job] = relationship(back_populates="steps")

    __table_args__ = (UniqueConstraint("job_id", "name"),)

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    def reset(self) -> None:
        self.status = StepStatus.PENDING
        self.exit_code = None
        self.started_at = None
        self.finished_at = None
        self.stderr_tail = None
