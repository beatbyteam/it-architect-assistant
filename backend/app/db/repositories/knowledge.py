from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.db.enums import (
    DocumentDeltaKind,
    KnowledgeBaseKind,
    KnowledgeBaseStatus,
    KnowledgeUpdateStatus,
    KnowledgeVersionStatus,
    SourceDocumentStatus,
    SourceProcessingStatus,
    SourceStatus,
)
from app.db.models.knowledge import (
    DocumentChunk,
    DocumentDelta,
    DocumentExtractedItem,
    DocumentSnapshot,
    EmbeddingSpace,
    KnowledgeBase,
    KnowledgeBaseSelection,
    KnowledgeFragment,
    KnowledgeFragmentEmbedding,
    KnowledgeSource,
    KnowledgeUpdateRun,
    KnowledgeVersion,
    KnowledgeVersionDocument,
    SourceDocument,
    SourceProcessingResult,
)
from app.db.repositories.base import Repository

TERMINAL_UPDATE_STATUSES = {
    KnowledgeUpdateStatus.COMPLETED,
    KnowledgeUpdateStatus.COMPLETED_WITH_WARNINGS,
    KnowledgeUpdateStatus.FAILED,
    KnowledgeUpdateStatus.CANCELED,
}


class KnowledgeBaseRepository(Repository[KnowledgeBase]):
    model = KnowledgeBase

    def get_by_code(self, code: str, owner_user_id: str | None = None) -> KnowledgeBase | None:
        statement = select(KnowledgeBase).where(KnowledgeBase.code == code)
        if owner_user_id is not None:
            statement = statement.where(
                or_(
                    KnowledgeBase.kind == KnowledgeBaseKind.SYSTEM_MANDATORY,
                    KnowledgeBase.owner_user_id == owner_user_id,
                    KnowledgeBase.owner_user_id.is_(None),
                )
            )
        return self.session.scalar(statement)

    def list_visible(
        self, *, include_archived: bool = False, owner_user_id: str | None = None
    ) -> list[KnowledgeBase]:
        statement = select(KnowledgeBase)
        if not include_archived:
            statement = statement.where(KnowledgeBase.status != KnowledgeBaseStatus.ARCHIVED)
        if owner_user_id is not None:
            statement = statement.where(
                or_(
                    KnowledgeBase.kind == KnowledgeBaseKind.SYSTEM_MANDATORY,
                    KnowledgeBase.owner_user_id == owner_user_id,
                    KnowledgeBase.owner_user_id.is_(None),
                )
            )
        statement = statement.order_by(KnowledgeBase.kind.asc(), KnowledgeBase.created_at.asc())
        return list(self.session.scalars(statement))

    def list_user_managed(self, owner_user_id: str | None = None) -> list[KnowledgeBase]:
        statement = (
            select(KnowledgeBase)
            .where(
                KnowledgeBase.kind == KnowledgeBaseKind.USER_MANAGED,
                KnowledgeBase.status != KnowledgeBaseStatus.ARCHIVED,
            )
            .order_by(KnowledgeBase.created_at.asc())
        )
        if owner_user_id is not None:
            statement = statement.where(
                or_(
                    KnowledgeBase.owner_user_id == owner_user_id,
                    KnowledgeBase.owner_user_id.is_(None),
                )
            )
        return list(self.session.scalars(statement))


class KnowledgeBaseSelectionRepository(Repository[KnowledgeBaseSelection]):
    model = KnowledgeBaseSelection

    def get_for_scope(self, selection_scope: str = "generation") -> KnowledgeBaseSelection | None:
        statement = (
            select(KnowledgeBaseSelection)
            .where(KnowledgeBaseSelection.selection_scope == selection_scope)
            .options(
                selectinload(KnowledgeBaseSelection.selected_knowledge_base),
                selectinload(KnowledgeBaseSelection.selected_knowledge_version),
            )
        )
        return self.session.scalar(statement)


class EmbeddingSpaceRepository(Repository[EmbeddingSpace]):
    model = EmbeddingSpace

    def get_active(self) -> EmbeddingSpace | None:
        return self.session.scalar(select(EmbeddingSpace).where(EmbeddingSpace.is_active.is_(True)))

    def get_by_code(self, code: str) -> EmbeddingSpace | None:
        return self.session.scalar(select(EmbeddingSpace).where(EmbeddingSpace.code == code))

    def list_visible(self) -> list[EmbeddingSpace]:
        return list(
            self.session.scalars(select(EmbeddingSpace).order_by(EmbeddingSpace.created_at.asc()))
        )


class KnowledgeFragmentEmbeddingRepository(Repository[KnowledgeFragmentEmbedding]):
    model = KnowledgeFragmentEmbedding

    def list_for_fragment(self, fragment_id: UUID | str) -> list[KnowledgeFragmentEmbedding]:
        statement = select(KnowledgeFragmentEmbedding).where(
            KnowledgeFragmentEmbedding.fragment_id == fragment_id
        )
        return list(self.session.scalars(statement))

    def list_for_version(
        self, knowledge_version_id: UUID | str
    ) -> list[KnowledgeFragmentEmbedding]:
        statement = (
            select(KnowledgeFragmentEmbedding)
            .join(
                KnowledgeFragment,
                KnowledgeFragment.fragment_id == KnowledgeFragmentEmbedding.fragment_id,
            )
            .where(KnowledgeFragment.knowledge_version_id == knowledge_version_id)
        )
        return list(self.session.scalars(statement))


class KnowledgeSourceRepository(Repository[KnowledgeSource]):
    model = KnowledgeSource

    def list_active(self, *, knowledge_base_id: UUID | str | None = None) -> list[KnowledgeSource]:
        statement = select(KnowledgeSource).where(KnowledgeSource.status == SourceStatus.ACTIVE)
        if knowledge_base_id is not None:
            statement = statement.where(KnowledgeSource.knowledge_base_id == knowledge_base_id)
        return list(self.session.scalars(statement))

    def list_for_base(
        self, knowledge_base_id: UUID | str, *, include_archived: bool = False
    ) -> list[KnowledgeSource]:
        return self.list_visible(
            include_archived=include_archived, knowledge_base_id=knowledge_base_id
        )

    def list_visible(
        self,
        *,
        include_archived: bool = False,
        knowledge_base_id: UUID | str | None = None,
        owner_user_id: str | None = None,
    ) -> list[KnowledgeSource]:
        statement = select(KnowledgeSource)
        if owner_user_id is not None:
            statement = statement.join(
                KnowledgeBase, KnowledgeBase.knowledge_base_id == KnowledgeSource.knowledge_base_id
            )
            statement = statement.where(
                or_(
                    KnowledgeBase.kind == KnowledgeBaseKind.SYSTEM_MANDATORY,
                    KnowledgeBase.owner_user_id == owner_user_id,
                    KnowledgeBase.owner_user_id.is_(None),
                )
            )
        if knowledge_base_id is not None:
            statement = statement.where(KnowledgeSource.knowledge_base_id == knowledge_base_id)
        if not include_archived:
            statement = statement.where(KnowledgeSource.status != SourceStatus.ARCHIVED)
        statement = statement.order_by(KnowledgeSource.created_at.desc())
        return list(self.session.scalars(statement))


class SourceDocumentRepository(Repository[SourceDocument]):
    model = SourceDocument

    def list_for_source(
        self, source_id: UUID | str, *, include_archived: bool = False
    ) -> list[SourceDocument]:
        statement = select(SourceDocument).where(SourceDocument.source_id == source_id)
        if not include_archived:
            statement = statement.where(SourceDocument.status != SourceDocumentStatus.ARCHIVED)
        statement = statement.order_by(SourceDocument.registered_at.desc())
        return list(self.session.scalars(statement))

    def list_for_sources(
        self, source_ids: list[UUID | str], *, include_archived: bool = False
    ) -> dict[str, list[SourceDocument]]:
        normalized_ids = [item for item in source_ids if item is not None]
        if not normalized_ids:
            return {}
        statement = select(SourceDocument).where(SourceDocument.source_id.in_(normalized_ids))
        if not include_archived:
            statement = statement.where(SourceDocument.status != SourceDocumentStatus.ARCHIVED)
        statement = statement.order_by(
            SourceDocument.source_id.asc(), SourceDocument.registered_at.desc()
        )
        grouped: dict[str, list[SourceDocument]] = defaultdict(list)
        for item in self.session.scalars(statement):
            grouped[str(item.source_id)].append(item)
        return dict(grouped)

    def get_by_source_and_uri(self, source_id: UUID | str, uri: str) -> SourceDocument | None:
        statement = select(SourceDocument).where(
            SourceDocument.source_id == source_id, SourceDocument.uri == uri
        )
        return self.session.scalar(statement)

    def list_latest_for_source(self, source_id: UUID | str) -> list[SourceDocument]:
        statement = select(SourceDocument).where(
            SourceDocument.source_id == source_id,
            SourceDocument.is_latest.is_(True),
            SourceDocument.status != SourceDocumentStatus.ARCHIVED,
        )
        return list(self.session.scalars(statement))

    def unset_latest_for_uri(
        self, *, source_id: UUID | str, uri: str, exclude_document_id: UUID | str | None = None
    ) -> None:
        documents = self.list_for_source(source_id, include_archived=True)
        for document in documents:
            if document.uri != uri:
                continue
            if exclude_document_id is not None and str(document.document_id) == str(
                exclude_document_id
            ):
                continue
            document.is_latest = False
            self.session.add(document)


class KnowledgeUpdateRunRepository(Repository[KnowledgeUpdateRun]):
    model = KnowledgeUpdateRun

    def get_latest_finished(
        self, *, knowledge_base_id: UUID | str | None = None
    ) -> KnowledgeUpdateRun | None:
        statement = select(KnowledgeUpdateRun).where(
            KnowledgeUpdateRun.status.in_(tuple(TERMINAL_UPDATE_STATUSES))
        )
        if knowledge_base_id is not None:
            statement = statement.where(KnowledgeUpdateRun.knowledge_base_id == knowledge_base_id)
        statement = statement.order_by(
            KnowledgeUpdateRun.finished_at.desc().nullslast(), KnowledgeUpdateRun.started_at.desc()
        )
        return self.session.scalar(statement)

    def get_running(
        self, *, knowledge_base_id: UUID | str | None = None
    ) -> KnowledgeUpdateRun | None:
        statement = select(KnowledgeUpdateRun).where(
            KnowledgeUpdateRun.status.not_in(tuple(TERMINAL_UPDATE_STATUSES))
        )
        if knowledge_base_id is not None:
            statement = statement.where(KnowledgeUpdateRun.knowledge_base_id == knowledge_base_id)
        return self.session.scalar(statement)

    def list_recent(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: KnowledgeUpdateStatus | None = None,
        knowledge_base_id: UUID | str | None = None,
    ) -> list[KnowledgeUpdateRun]:
        statement = select(KnowledgeUpdateRun)
        if status is not None:
            statement = statement.where(KnowledgeUpdateRun.status == status)
        if knowledge_base_id is not None:
            statement = statement.where(KnowledgeUpdateRun.knowledge_base_id == knowledge_base_id)
        statement = (
            statement.order_by(KnowledgeUpdateRun.started_at.desc()).offset(offset).limit(limit)
        )
        return list(self.session.scalars(statement))


class SourceProcessingResultRepository(Repository[SourceProcessingResult]):
    model = SourceProcessingResult

    def get_for_scope(
        self, *, update_run_id, source_id, document_id=None
    ) -> SourceProcessingResult | None:
        document_clause = (
            SourceProcessingResult.document_id.is_(None)
            if document_id is None
            else SourceProcessingResult.document_id == document_id
        )
        statement = select(SourceProcessingResult).where(
            SourceProcessingResult.update_run_id == update_run_id,
            SourceProcessingResult.source_id == source_id,
            document_clause,
        )
        return self.session.scalar(statement)

    def list_for_run(self, update_run_id) -> list[SourceProcessingResult]:
        statement = select(SourceProcessingResult).where(
            SourceProcessingResult.update_run_id == update_run_id
        )
        return list(self.session.scalars(statement))

    def get_latest_for_source(self, source_id) -> SourceProcessingResult | None:
        statement = (
            select(SourceProcessingResult)
            .where(
                SourceProcessingResult.source_id == source_id,
                SourceProcessingResult.document_id.is_(None),
            )
            .order_by(SourceProcessingResult.processed_at.desc())
        )
        return self.session.scalar(statement)

    def get_latest_for_sources(
        self, source_ids: list[UUID | str]
    ) -> dict[str, SourceProcessingResult]:
        normalized_ids = [item for item in source_ids if item is not None]
        if not normalized_ids:
            return {}
        statement = (
            select(SourceProcessingResult)
            .where(
                SourceProcessingResult.source_id.in_(normalized_ids),
                SourceProcessingResult.document_id.is_(None),
            )
            .order_by(
                SourceProcessingResult.source_id.asc(), SourceProcessingResult.processed_at.desc()
            )
        )
        latest: dict[str, SourceProcessingResult] = {}
        for item in self.session.scalars(statement):
            latest.setdefault(str(item.source_id), item)
        return latest

    def get_latest_for_document(self, document_id) -> SourceProcessingResult | None:
        statement = (
            select(SourceProcessingResult)
            .where(SourceProcessingResult.document_id == document_id)
            .order_by(SourceProcessingResult.processed_at.desc())
        )
        return self.session.scalar(statement)

    def list_recent_for_source(self, source_id, *, limit: int = 20) -> list[SourceProcessingResult]:
        statement = (
            select(SourceProcessingResult)
            .where(
                SourceProcessingResult.source_id == source_id,
                SourceProcessingResult.document_id.is_(None),
            )
            .order_by(SourceProcessingResult.processed_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def get_latest_success_for_source(self, source_id) -> SourceProcessingResult | None:
        statement = (
            select(SourceProcessingResult)
            .where(
                SourceProcessingResult.source_id == source_id,
                SourceProcessingResult.document_id.is_(None),
                SourceProcessingResult.status.not_in(
                    (SourceProcessingStatus.FAILED, SourceProcessingStatus.SKIPPED)
                ),
            )
            .order_by(SourceProcessingResult.processed_at.desc())
        )
        return self.session.scalar(statement)

    def get_latest_success_for_sources(
        self, source_ids: list[UUID | str]
    ) -> dict[str, SourceProcessingResult]:
        normalized_ids = [item for item in source_ids if item is not None]
        if not normalized_ids:
            return {}
        statement = (
            select(SourceProcessingResult)
            .where(
                SourceProcessingResult.source_id.in_(normalized_ids),
                SourceProcessingResult.document_id.is_(None),
                SourceProcessingResult.status.not_in(
                    (SourceProcessingStatus.FAILED, SourceProcessingStatus.SKIPPED)
                ),
            )
            .order_by(
                SourceProcessingResult.source_id.asc(), SourceProcessingResult.processed_at.desc()
            )
        )
        latest: dict[str, SourceProcessingResult] = {}
        for item in self.session.scalars(statement):
            latest.setdefault(str(item.source_id), item)
        return latest


class DocumentSnapshotRepository(Repository[DocumentSnapshot]):
    model = DocumentSnapshot

    def get_latest_for_document(
        self, document_id: UUID | str, *, knowledge_version_id: UUID | str | None = None
    ) -> DocumentSnapshot | None:
        statement = select(DocumentSnapshot).where(DocumentSnapshot.document_id == document_id)
        if knowledge_version_id is not None:
            statement = statement.where(
                DocumentSnapshot.knowledge_version_id == knowledge_version_id
            )
        statement = statement.options(selectinload(DocumentSnapshot.chunks)).order_by(
            DocumentSnapshot.created_at.desc()
        )
        return self.session.scalar(statement)

    def find_reusable_by_checksum(
        self,
        checksum: str,
        *,
        embedding_space_id: UUID | str | None = None,
        exclude_knowledge_version_id: UUID | str | None = None,
    ) -> DocumentSnapshot | None:
        statement = (
            select(DocumentSnapshot)
            .join(
                KnowledgeVersion,
                KnowledgeVersion.knowledge_version_id == DocumentSnapshot.knowledge_version_id,
            )
            .where(
                DocumentSnapshot.checksum == checksum,
                KnowledgeVersion.status.in_(
                    (
                        KnowledgeVersionStatus.ACTIVE,
                        KnowledgeVersionStatus.VALIDATED,
                        KnowledgeVersionStatus.ARCHIVED,
                    )
                ),
            )
            .options(selectinload(DocumentSnapshot.chunks))
            .order_by(DocumentSnapshot.created_at.desc())
        )
        if embedding_space_id is not None:
            statement = statement.where(KnowledgeVersion.embedding_space_id == embedding_space_id)
        if exclude_knowledge_version_id is not None:
            statement = statement.where(
                DocumentSnapshot.knowledge_version_id != exclude_knowledge_version_id
            )
        return self.session.scalar(statement)


class DocumentChunkRepository(Repository[DocumentChunk]):
    model = DocumentChunk

    def list_for_snapshot(self, document_snapshot_id: UUID | str) -> list[DocumentChunk]:
        statement = (
            select(DocumentChunk)
            .where(DocumentChunk.document_snapshot_id == document_snapshot_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        return list(self.session.scalars(statement))


class KnowledgeVersionRepository(Repository[KnowledgeVersion]):
    model = KnowledgeVersion

    def get_by_update_run_id(self, update_run_id) -> KnowledgeVersion | None:
        statement = select(KnowledgeVersion).where(KnowledgeVersion.update_run_id == update_run_id)
        return self.session.scalar(statement)

    def get_active(
        self, *, knowledge_base_id: UUID | str | None = None, eager: bool = False
    ) -> KnowledgeVersion | None:
        statement = select(KnowledgeVersion).where(
            KnowledgeVersion.status == KnowledgeVersionStatus.ACTIVE
        )
        if knowledge_base_id is not None:
            statement = statement.where(KnowledgeVersion.knowledge_base_id == knowledge_base_id)
        if eager:
            statement = statement.options(
                selectinload(KnowledgeVersion.version_documents).selectinload(
                    KnowledgeVersionDocument.document
                ),
                selectinload(KnowledgeVersion.embedding_space),
            )
        return self.session.scalar(statement)

    def get_active_for_update(
        self, *, knowledge_base_id: UUID | str | None = None, eager: bool = False
    ) -> KnowledgeVersion | None:
        statement = select(KnowledgeVersion).where(
            KnowledgeVersion.status == KnowledgeVersionStatus.ACTIVE
        )
        if knowledge_base_id is not None:
            statement = statement.where(KnowledgeVersion.knowledge_base_id == knowledge_base_id)
        statement = statement.with_for_update()
        if eager:
            statement = statement.options(
                selectinload(KnowledgeVersion.version_documents).selectinload(
                    KnowledgeVersionDocument.document
                ),
                selectinload(KnowledgeVersion.embedding_space),
            )
        return self.session.scalar(statement)

    def get_for_update(self, knowledge_version_id) -> KnowledgeVersion | None:
        statement = (
            select(KnowledgeVersion)
            .where(KnowledgeVersion.knowledge_version_id == knowledge_version_id)
            .with_for_update()
        )
        return self.session.scalar(statement)

    def list_candidates(
        self, *, knowledge_base_id: UUID | str | None = None
    ) -> list[KnowledgeVersion]:
        statement = (
            select(KnowledgeVersion)
            .where(
                KnowledgeVersion.status.in_(
                    (
                        KnowledgeVersionStatus.VALIDATED,
                        KnowledgeVersionStatus.REJECTED,
                        KnowledgeVersionStatus.DRAFT,
                    )
                )
            )
            .order_by(KnowledgeVersion.created_at.desc())
        )
        if knowledge_base_id is not None:
            statement = statement.where(KnowledgeVersion.knowledge_base_id == knowledge_base_id)
        return list(self.session.scalars(statement))

    def get_with_documents(self, knowledge_version_id) -> KnowledgeVersion | None:
        statement = (
            select(KnowledgeVersion)
            .where(KnowledgeVersion.knowledge_version_id == knowledge_version_id)
            .options(
                selectinload(KnowledgeVersion.knowledge_base),
                selectinload(KnowledgeVersion.embedding_space),
                selectinload(KnowledgeVersion.version_documents)
                .selectinload(KnowledgeVersionDocument.document)
                .selectinload(SourceDocument.source),
            )
        )
        return self.session.scalar(statement)

    def list_visible(
        self, *, knowledge_base_id: UUID | str | None = None
    ) -> list[KnowledgeVersion]:
        statement = select(KnowledgeVersion).options(selectinload(KnowledgeVersion.embedding_space))
        if knowledge_base_id is not None:
            statement = statement.where(KnowledgeVersion.knowledge_base_id == knowledge_base_id)
        statement = statement.order_by(KnowledgeVersion.created_at.desc())
        return list(self.session.scalars(statement))


class DocumentExtractedItemRepository(Repository[DocumentExtractedItem]):
    model = DocumentExtractedItem

    def list_for_document(
        self, document_id: UUID | str, *, knowledge_version_id: UUID | str | None = None
    ) -> list[DocumentExtractedItem]:
        statement = select(DocumentExtractedItem).where(
            DocumentExtractedItem.document_id == document_id
        )
        if knowledge_version_id is not None:
            statement = statement.where(
                DocumentExtractedItem.knowledge_version_id == knowledge_version_id
            )
        statement = statement.order_by(DocumentExtractedItem.created_at.asc())
        return list(self.session.scalars(statement))


class DocumentDeltaRepository(Repository[DocumentDelta]):
    model = DocumentDelta

    def list_for_run(self, update_run_id: UUID | str) -> list[DocumentDelta]:
        statement = (
            select(DocumentDelta)
            .where(DocumentDelta.update_run_id == update_run_id)
            .order_by(DocumentDelta.created_at.asc())
        )
        return list(self.session.scalars(statement))

    def summarize_for_run(self, update_run_id: UUID | str) -> dict[str, int]:
        items = self.list_for_run(update_run_id)
        summary = {kind.value: 0 for kind in DocumentDeltaKind}
        for item in items:
            key = getattr(item.delta_kind, "value", item.delta_kind)
            summary[key] = summary.get(key, 0) + 1
        return summary
