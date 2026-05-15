from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.db.models.publication import PublishedArtifact
from app.db.repositories.publication import PublishedArtifactRepository


class PublicationArtifactService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.artifacts = PublishedArtifactRepository(session)

    @staticmethod
    def _build_version_hash(
        *,
        artifact_type: str,
        target_type: str,
        target_id: str,
        revision_no: int,
        rendered_html: str,
        rendered_markdown: str | None,
    ) -> str:
        payload = "||".join(
            [
                artifact_type,
                target_type,
                str(target_id),
                str(revision_no),
                rendered_html,
                rendered_markdown or "",
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def publish(
        self,
        *,
        artifact_type: str,
        target_type: str,
        target_id: str,
        rendered_html: str,
        rendered_markdown: str | None = None,
        metadata: dict[str, Any] | None = None,
        created_by_user_id: str | None = None,
        published_at: datetime | None = None,
    ) -> PublishedArtifact:
        published_at = published_at or datetime.now(UTC)
        begin_nested = getattr(self.session, "begin_nested", None)
        last_error: IntegrityError | None = None
        for _attempt in range(3):
            try:
                if callable(begin_nested):
                    with begin_nested():
                        self.artifacts.supersede_current(
                            target_type=target_type, target_id=target_id
                        )
                        revision_no = self.artifacts.get_next_revision_no(
                            target_type=target_type, target_id=target_id
                        )
                        artifact = PublishedArtifact(
                            artifact_type=artifact_type,
                            target_type=target_type,
                            target_id=str(target_id),
                            revision_no=revision_no,
                            state="published",
                            created_by_user_id=created_by_user_id,
                            rendered_markdown=rendered_markdown,
                            rendered_html=rendered_html,
                            artifact_metadata=metadata or {},
                            published_at=published_at,
                            version_hash=self._build_version_hash(
                                artifact_type=artifact_type,
                                target_type=target_type,
                                target_id=str(target_id),
                                revision_no=revision_no,
                                rendered_html=rendered_html,
                                rendered_markdown=rendered_markdown,
                            ),
                        )
                        self.session.add(artifact)
                        self.session.flush()
                    self.session.refresh(artifact)
                    return artifact
                self.artifacts.supersede_current(target_type=target_type, target_id=target_id)
                revision_no = self.artifacts.get_next_revision_no(
                    target_type=target_type, target_id=target_id
                )
                artifact = PublishedArtifact(
                    artifact_type=artifact_type,
                    target_type=target_type,
                    target_id=str(target_id),
                    revision_no=revision_no,
                    state="published",
                    created_by_user_id=created_by_user_id,
                    rendered_markdown=rendered_markdown,
                    rendered_html=rendered_html,
                    artifact_metadata=metadata or {},
                    published_at=published_at,
                    version_hash=self._build_version_hash(
                        artifact_type=artifact_type,
                        target_type=target_type,
                        target_id=str(target_id),
                        revision_no=revision_no,
                        rendered_html=rendered_html,
                        rendered_markdown=rendered_markdown,
                    ),
                )
                self.session.add(artifact)
                self.session.flush()
                self.session.refresh(artifact)
                return artifact
            except IntegrityError as exc:
                last_error = exc
                if not callable(begin_nested):
                    self.session.rollback()
        raise ConflictError(
            "Concurrent publication detected; please retry publication",
            error_code="PUBLICATION_REVISION_CONFLICT",
        ) from last_error

    def get_current(self, *, target_type: str, target_id: str) -> PublishedArtifact | None:
        return self.artifacts.get_latest_for_target(target_type=target_type, target_id=target_id)

    def list_revisions(self, *, target_type: str, target_id: str) -> list[PublishedArtifact]:
        return self.artifacts.list_for_target(target_type=target_type, target_id=target_id)
