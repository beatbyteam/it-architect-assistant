from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.models.publication import PublishedArtifact
from app.db.repositories.base import Repository


class PublishedArtifactRepository(Repository[PublishedArtifact]):
    model = PublishedArtifact

    def list_for_target(self, *, target_type: str, target_id: str) -> list[PublishedArtifact]:
        statement = (
            select(PublishedArtifact)
            .where(
                PublishedArtifact.target_type == target_type,
                PublishedArtifact.target_id == str(target_id),
            )
            .order_by(
                PublishedArtifact.revision_no.desc(),
                PublishedArtifact.published_at.desc(),
                PublishedArtifact.created_at.desc(),
            )
        )
        return list(self.session.scalars(statement))

    def get_latest_for_target(
        self, *, target_type: str, target_id: str, include_superseded: bool = False
    ) -> PublishedArtifact | None:
        statement = select(PublishedArtifact).where(
            PublishedArtifact.target_type == target_type,
            PublishedArtifact.target_id == str(target_id),
        )
        if not include_superseded:
            statement = statement.where(PublishedArtifact.state == "published")
        statement = statement.order_by(
            PublishedArtifact.revision_no.desc(),
            PublishedArtifact.published_at.desc(),
            PublishedArtifact.created_at.desc(),
        )
        return self.session.scalar(statement)

    def get_next_revision_no(self, *, target_type: str, target_id: str) -> int:
        statement = select(func.coalesce(func.max(PublishedArtifact.revision_no), 0)).where(
            PublishedArtifact.target_type == target_type,
            PublishedArtifact.target_id == str(target_id),
        )
        value = self.session.scalar(statement) or 0
        return int(value) + 1

    def supersede_current(self, *, target_type: str, target_id: str) -> list[PublishedArtifact]:
        now = datetime.now(UTC)
        items = self.list_for_target(target_type=target_type, target_id=target_id)
        updated: list[PublishedArtifact] = []
        for item in items:
            if item.state == "published":
                item.state = "superseded"
                item.superseded_at = now
                self.session.add(item)
                updated.append(item)
        return updated
