from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import uuid_primary_key


class PublishedArtifact(Base):
    __tablename__ = "published_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "target_type", "target_id", "revision_no", name="uq_published_artifacts_target_revision"
        ),
        Index("ix_published_artifacts_target", "target_type", "target_id", "state"),
        Index("ix_published_artifacts_published_at", "published_at"),
    )

    published_artifact_id: Mapped[str] = uuid_primary_key("published_artifact_id")
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        String(50), nullable=False, default="published", server_default="published"
    )
    created_by_user_id: Mapped[str | None] = mapped_column(String(100))
    rendered_markdown: Mapped[str | None] = mapped_column(Text)
    rendered_html: Mapped[str] = mapped_column(Text, nullable=False)
    version_hash: Mapped[str | None] = mapped_column(String(64))
    artifact_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
