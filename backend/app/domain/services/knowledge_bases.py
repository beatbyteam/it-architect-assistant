# ruff: noqa: E501
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AuditSeverity,
    KnowledgeBaseKind,
    KnowledgeBaseStatus,
    KnowledgeVersionStatus,
)
from app.db.models.knowledge import KnowledgeBase, KnowledgeBaseSelection, KnowledgeVersion
from app.db.repositories.generation import GenerationRunRepository
from app.db.repositories.knowledge import (
    KnowledgeBaseRepository,
    KnowledgeBaseSelectionRepository,
    KnowledgeSourceRepository,
    KnowledgeUpdateRunRepository,
    KnowledgeVersionRepository,
    SourceDocumentRepository,
)
from app.domain.services.audit import AuditService
from app.domain.services.knowledge.policies import is_generation_selectable_version
from app.domain.services.principal_keys import principal_actor_id

MANDATORY_BASE_CODE = "mandatory_architecture_baseline"
DEFAULT_USER_BASE_CODE = "default_user_knowledge_base"
GENERATION_SELECTION_SCOPE = "generation"


def _owner_key_for_principal(principal: AuthPrincipal | None) -> str | None:
    if principal is None:
        return None
    return principal_actor_id(principal) or "local"


def _selection_scope_for_principal(principal: AuthPrincipal | None) -> str:
    owner_key = _owner_key_for_principal(principal)
    if owner_key is None:
        return GENERATION_SELECTION_SCOPE
    return f"{GENERATION_SELECTION_SCOPE}:{owner_key}"


def _safe_code_fragment(value: str | None) -> str:
    raw = str(value or "knowledge_base").strip().lower().replace("-", " ")
    parts = [part for part in raw.split() if part]
    return "_".join(parts)[:80] or "knowledge_base"


def _default_user_base_code_for_principal(principal: AuthPrincipal | None) -> str:
    owner_key = _owner_key_for_principal(principal)
    if owner_key is None:
        return DEFAULT_USER_BASE_CODE
    return f"{DEFAULT_USER_BASE_CODE}__{_safe_code_fragment(owner_key)}"


@dataclass(slots=True)
class EffectiveKnowledgeScope:
    mandatory_base: KnowledgeBase | None
    mandatory_version: KnowledgeVersion | None
    selected_user_base: KnowledgeBase
    selected_user_version: KnowledgeVersion | None

    def selected_generation_version(self) -> KnowledgeVersion | None:
        return self.selected_user_version or self.mandatory_version

    def as_dict(self) -> dict[str, Any]:
        return {
            "mandatory_base": _serialize_base(self.mandatory_base),
            "mandatory_version": _serialize_version(self.mandatory_version),
            "selected_user_base": _serialize_base(self.selected_user_base),
            "selected_user_version": _serialize_version(self.selected_user_version),
            "effective_version_ids": [
                item
                for item in [
                    str(self.mandatory_version.knowledge_version_id)
                    if self.mandatory_version
                    else None,
                    str(self.selected_user_version.knowledge_version_id)
                    if self.selected_user_version
                    else None,
                ]
                if item is not None
            ],
        }


class KnowledgeBaseService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.bases = KnowledgeBaseRepository(session)
        self.selections = KnowledgeBaseSelectionRepository(session)
        self.versions = KnowledgeVersionRepository(session)
        self.sources = KnowledgeSourceRepository(session)
        self.documents = SourceDocumentRepository(session)
        self.update_runs = KnowledgeUpdateRunRepository(session)
        self.generation_runs = GenerationRunRepository(session)
        self.audit = AuditService(session)

    def _is_base_accessible(self, base: KnowledgeBase, principal: AuthPrincipal | None) -> bool:
        status_value = getattr(
            getattr(base, "status", None), "value", getattr(base, "status", None)
        )
        if status_value == KnowledgeBaseStatus.ARCHIVED.value:
            return False
        if base.kind == KnowledgeBaseKind.SYSTEM_MANDATORY:
            return True
        owner_key = _owner_key_for_principal(principal)
        base_owner = getattr(base, "owner_user_id", None)
        if owner_key is None:
            return base_owner is None
        return base_owner in {None, owner_key}

    def _assert_base_access(self, base: KnowledgeBase, principal: AuthPrincipal | None) -> None:
        if not self._is_base_accessible(base, principal):
            raise AuthorizationError("Access denied to the requested knowledge base")

    def _assert_generation_selection_unlocked(self, principal: AuthPrincipal | None) -> None:
        repository = getattr(self, "generation_runs", None)
        if repository is None:
            return
        running = repository.get_running_for_owner(principal_actor_id(principal))
        if running is None:
            return
        raise ValidationError(
            "Knowledge base cannot be changed while a solution generation is running",
            error_code="KNOWLEDGE_BASE_SELECTION_GENERATION_IN_PROGRESS",
        )

    def ensure_system_bases(
        self, principal: AuthPrincipal | None = None
    ) -> tuple[KnowledgeBase, KnowledgeBase | None]:
        changed = False
        mandatory = self.bases.get_by_code(MANDATORY_BASE_CODE)
        if mandatory is None:
            mandatory = KnowledgeBase(
                code=MANDATORY_BASE_CODE,
                name="Mandatory Architecture Baseline",
                description="System mandatory baseline for TOGAF and ArchiMate 3.2.",
                kind=KnowledgeBaseKind.SYSTEM_MANDATORY,
                status=KnowledgeBaseStatus.ACTIVE,
                owner_user_id=None,
            )
            self.bases.add(mandatory)
            self.session.flush()
            changed = True
        selection_scope = _selection_scope_for_principal(principal)
        selection = self.selections.get_for_scope(selection_scope)
        if selection is None:
            selection = KnowledgeBaseSelection(
                selection_scope=selection_scope,
                selected_knowledge_base_id=mandatory.knowledge_base_id,
                selected_knowledge_version_id=None,
            )
            self.selections.add(selection)
            self.session.flush()
            changed = True
        if changed:
            self.session.commit()
            self.session.refresh(mandatory)
        return mandatory, None

    def _get_existing_system_bases(
        self, principal: AuthPrincipal | None = None
    ) -> tuple[KnowledgeBase | None, KnowledgeBase | None]:
        mandatory = self.bases.get_by_code(MANDATORY_BASE_CODE)
        try:
            default_user = self.bases.get_by_code(
                _default_user_base_code_for_principal(principal),
                owner_user_id=_owner_key_for_principal(principal),
            )
        except TypeError:
            default_user = self.bases.get_by_code(_default_user_base_code_for_principal(principal))
        return mandatory, default_user

    def get_mandatory_base(self, principal: AuthPrincipal | None = None) -> KnowledgeBase:
        base, _ = self._get_existing_system_bases(principal)
        if base is None:
            raise NotFoundError("KnowledgeBase", MANDATORY_BASE_CODE)
        return base

    def get_default_user_base(self, principal: AuthPrincipal | None = None) -> KnowledgeBase:
        _, base = self._get_existing_system_bases(principal)
        if base is None or not self._is_base_accessible(base, principal):
            raise NotFoundError("KnowledgeBase", _default_user_base_code_for_principal(principal))
        return base

    def _selected_version_for_base(
        self,
        *,
        selection: KnowledgeBaseSelection | None,
        base: KnowledgeBase,
        principal: AuthPrincipal | None = None,
    ) -> KnowledgeVersion | None:
        if selection is None or selection.selected_knowledge_version_id is None:
            return None
        if str(selection.selected_knowledge_base_id) != str(base.knowledge_base_id):
            return None
        version = self.versions.get(selection.selected_knowledge_version_id)
        if version is None:
            return None
        if str(version.knowledge_base_id) != str(base.knowledge_base_id):
            return None
        if not is_generation_selectable_version(version):
            return None
        if not self._is_base_accessible(base, principal):
            return None
        return version

    def list_payloads(self, principal: AuthPrincipal | None = None) -> list[dict[str, Any]]:
        selection = self.selections.get_for_scope(_selection_scope_for_principal(principal))
        effective_scope = self.get_existing_effective_scope(principal)
        selected_base_id = (
            str(effective_scope.selected_user_base.knowledge_base_id)
            if effective_scope is not None and effective_scope.selected_user_base is not None
            else str(selection.selected_knowledge_base_id)
            if selection is not None and selection.selected_knowledge_base_id is not None
            else None
        )
        effective_selected_version = (
            effective_scope.selected_user_version if effective_scope is not None else None
        )
        items: list[dict[str, Any]] = []
        try:
            visible_bases = list(
                self.bases.list_visible(owner_user_id=_owner_key_for_principal(principal))
            )
        except TypeError:
            visible_bases = list(self.bases.list_visible())
        for base in visible_bases:
            active_version = self.versions.get_active(knowledge_base_id=base.knowledge_base_id)
            payload = _serialize_base(base) or {}
            payload.update(self._base_stats(base))
            is_mandatory_base = base.kind == KnowledgeBaseKind.SYSTEM_MANDATORY
            payload_selected = str(base.knowledge_base_id) == selected_base_id
            selected_version = (
                (effective_scope.mandatory_version if effective_scope is not None else active_version)
                if payload_selected and is_mandatory_base
                else (
                    effective_selected_version
                    if payload_selected and effective_scope is not None
                    else self._selected_version_for_base(
                        selection=selection, base=base, principal=principal
                    )
                )
            )
            payload.update(
                {
                    "active_knowledge_version_id": str(active_version.knowledge_version_id)
                    if active_version
                    else None,
                    "active_version_no": active_version.version_no if active_version else None,
                    "selected_for_generation": payload_selected,
                    "selected_knowledge_version_id": str(selected_version.knowledge_version_id)
                    if payload_selected and selected_version is not None
                    else None,
                    "selected_knowledge_version_no": selected_version.version_no
                    if payload_selected and selected_version is not None
                    else None,
                    "active_embedding_space_id": str(
                        getattr(active_version, "embedding_space_id", None)
                    )
                    if active_version and getattr(active_version, "embedding_space_id", None)
                    else None,
                    "active_embedding_space_code": getattr(
                        getattr(active_version, "embedding_space", None), "code", None
                    )
                    if active_version
                    else None,
                }
            )
            items.append(payload)
        return items

    def create_user_base(
        self, *, name: str, description: str | None, principal: AuthPrincipal
    ) -> KnowledgeBase:
        owner_key = _owner_key_for_principal(principal)
        code_seed = _safe_code_fragment(name)
        code = f"user_{code_seed[:80]}__{_safe_code_fragment(owner_key)}"
        suffix = 1
        while self.bases.get_by_code(code, owner_user_id=owner_key) is not None:
            suffix += 1
            code = f"user_{code_seed[:70]}_{suffix}__{_safe_code_fragment(owner_key)}"
        base = KnowledgeBase(
            code=code,
            name=name,
            description=description,
            kind=KnowledgeBaseKind.USER_MANAGED,
            status=KnowledgeBaseStatus.ACTIVE,
            owner_user_id=owner_key,
        )
        self.bases.add(base)
        self.session.flush()
        self.audit.record(
            event_type="knowledge.base.created",
            target_type="knowledge_base",
            target_id=base.knowledge_base_id,
            message=f"Knowledge base '{name}' created",
            actor_user_id=principal_actor_id(principal),
        )
        self.session.commit()
        self.session.refresh(base)
        return base

    def update_user_base(
        self,
        knowledge_base_id: str,
        *,
        name: str | None,
        description: str | None,
        status: KnowledgeBaseStatus | None,
        principal: AuthPrincipal,
    ) -> KnowledgeBase:
        try:
            base = self.get_base(knowledge_base_id, principal)
        except TypeError:
            base = self.get_base(knowledge_base_id)
        if base.kind != KnowledgeBaseKind.USER_MANAGED:
            raise ValidationError(
                "System mandatory knowledge base cannot be modified via public API",
                error_code="KNOWLEDGE_BASE_IMMUTABLE",
            )
        if name is not None:
            base.name = name
        if description is not None:
            base.description = description
        if status is not None:
            base.status = status
        self.bases.add(base)
        self.audit.record(
            event_type="knowledge.base.updated",
            target_type="knowledge_base",
            target_id=base.knowledge_base_id,
            message=f"Knowledge base '{base.name}' updated",
            actor_user_id=principal_actor_id(principal),
            payload={"status": getattr(base.status, "value", base.status)},
        )
        self.session.commit()
        self.session.refresh(base)
        return base

    def get_base(
        self, knowledge_base_id: str, principal: AuthPrincipal | None = None
    ) -> KnowledgeBase:
        base = self.bases.get(knowledge_base_id)
        if base is None:
            raise NotFoundError("KnowledgeBase", knowledge_base_id)
        self._assert_base_access(base, principal)
        return base

    def get_base_payload(
        self, knowledge_base_id: str, principal: AuthPrincipal | None = None
    ) -> dict[str, Any]:
        try:
            base = self.get_base(knowledge_base_id, principal)
        except TypeError:
            base = self.get_base(knowledge_base_id)
        return self.build_base_payload(base, principal)

    def build_base_payload(
        self, base: KnowledgeBase, principal: AuthPrincipal | None = None
    ) -> dict[str, Any]:
        payload = _serialize_base(base) or {}
        payload.update(self._base_stats(base))
        payload["versions"] = [
            {
                **(_serialize_version(item) or {}),
                "is_active": item.status == KnowledgeVersionStatus.ACTIVE,
                "selectable_for_generation": is_generation_selectable_version(item),
            }
            for item in self.versions.list_visible(knowledge_base_id=base.knowledge_base_id)
        ]
        active = self.versions.get_active(knowledge_base_id=base.knowledge_base_id)
        selection = self.selections.get_for_scope(_selection_scope_for_principal(principal))
        effective_scope = self.get_existing_effective_scope(principal)
        selected_base_id = (
            str(effective_scope.selected_user_base.knowledge_base_id)
            if effective_scope is not None and effective_scope.selected_user_base is not None
            else str(selection.selected_knowledge_base_id)
            if selection is not None and selection.selected_knowledge_base_id is not None
            else None
        )
        is_selected_for_generation = str(base.knowledge_base_id) == selected_base_id
        selected_version = (
            (effective_scope.mandatory_version if effective_scope is not None else active)
            if is_selected_for_generation and base.kind == KnowledgeBaseKind.SYSTEM_MANDATORY
            else (
                effective_scope.selected_user_version
                if is_selected_for_generation and effective_scope is not None
                else self._selected_version_for_base(
                    selection=selection, base=base, principal=principal
                )
            )
        )
        payload["active_knowledge_version_id"] = (
            str(active.knowledge_version_id) if active else None
        )
        payload["active_version_no"] = active.version_no if active else None
        payload["active_embedding_space_id"] = (
            str(getattr(active, "embedding_space_id", None))
            if active and getattr(active, "embedding_space_id", None)
            else None
        )
        payload["active_embedding_space_code"] = (
            getattr(getattr(active, "embedding_space", None), "code", None) if active else None
        )
        payload["selected_for_generation"] = is_selected_for_generation
        payload["selected_knowledge_version_id"] = (
            str(selected_version.knowledge_version_id)
            if selected_version is not None and payload["selected_for_generation"]
            else None
        )
        payload["selected_knowledge_version_no"] = (
            selected_version.version_no
            if selected_version is not None and payload["selected_for_generation"]
            else None
        )
        return payload

    def _base_stats(self, base: KnowledgeBase) -> dict[str, Any]:
        sources = self.sources.list_for_base(base.knowledge_base_id)
        active_sources = [
            item for item in sources if getattr(item.status, "value", item.status) == "active"
        ]
        documents = []
        for source in sources:
            documents.extend(
                self.documents.list_for_source(source.source_id, include_archived=False)
            )
        latest_run = self.update_runs.get_latest_finished(knowledge_base_id=base.knowledge_base_id)
        successful_runs = [
            item
            for item in self.update_runs.list_recent(
                limit=50, knowledge_base_id=base.knowledge_base_id
            )
            if getattr(item.status, "value", item.status)
            in {"completed", "completed_with_warnings"}
        ]
        latest_success = successful_runs[0] if successful_runs else None
        summary = (
            dict((latest_run.summary or {}).get("quality_summary") or {})
            if latest_run is not None
            else {}
        )
        return {
            "source_count": len(sources),
            "active_source_count": len(active_sources),
            "document_count": len(documents),
            "latest_sync_at": latest_run.finished_at if latest_run is not None else None,
            "latest_sync_status": latest_run.status if latest_run is not None else None,
            "latest_sync_run_id": str(latest_run.update_run_id) if latest_run is not None else None,
            "latest_successful_sync_at": latest_success.finished_at
            if latest_success is not None
            else None,
            "last_sync_duration_sec": latest_run.duration_sec if latest_run is not None else None,
            "last_sync_error_count": int(summary.get("processing_error_count") or 0),
        }

    def select_user_base(
        self,
        knowledge_base_id: str,
        principal: AuthPrincipal,
        *,
        knowledge_version_id: str | None = None,
    ) -> KnowledgeBaseSelection:
        self._assert_generation_selection_unlocked(principal)
        try:
            base = self.get_base(knowledge_base_id, principal)
        except TypeError:
            base = self.get_base(knowledge_base_id)
        if base.kind not in {KnowledgeBaseKind.USER_MANAGED, KnowledgeBaseKind.SYSTEM_MANDATORY}:
            raise ValidationError(
                "Only user-managed or mandatory knowledge bases can be selected for generation",
                error_code="KNOWLEDGE_BASE_SELECTION_INVALID",
            )
        selection = self.selections.get_for_scope(_selection_scope_for_principal(principal))
        if selection is None:
            selection = KnowledgeBaseSelection(
                selection_scope=_selection_scope_for_principal(principal),
                selected_knowledge_base_id=base.knowledge_base_id,
            )
            self.selections.add(selection)
            self.session.flush()
        selection.selected_knowledge_base_id = base.knowledge_base_id
        if knowledge_version_id is not None:
            version = self.versions.get(knowledge_version_id)
            if version is None or str(version.knowledge_base_id) != str(base.knowledge_base_id):
                raise ValidationError(
                    "Selected knowledge version does not belong to the selected knowledge base",
                    error_code="KNOWLEDGE_BASE_SELECTION_VERSION_INVALID",
                )
            if not is_generation_selectable_version(version):
                raise ValidationError(
                    "Selected knowledge version is not eligible for generation",
                    error_code="KNOWLEDGE_BASE_SELECTION_VERSION_INELIGIBLE",
                )
            selection.selected_knowledge_version_id = version.knowledge_version_id
        else:
            selection.selected_knowledge_version_id = None
        if base.kind == KnowledgeBaseKind.SYSTEM_MANDATORY:
            selection.selected_knowledge_version_id = None
        selection.updated_by_user_id = principal_actor_id(principal)
        self.session.add(selection)
        self.audit.record(
            event_type="knowledge.base.selected",
            target_type="knowledge_base_selection",
            target_id=selection.knowledge_base_selection_id,
            message=f"Knowledge base '{base.name}' selected for generation",
            actor_user_id=principal_actor_id(principal),
            severity=AuditSeverity.INFO,
            payload={
                "knowledge_base_id": str(base.knowledge_base_id),
                "knowledge_version_id": knowledge_version_id,
            },
        )
        self.session.commit()
        self.session.refresh(selection)
        return selection

    def _resolve_effective_scope(
        self, principal: AuthPrincipal | None = None, *, ensure_defaults: bool
    ) -> EffectiveKnowledgeScope | None:
        if ensure_defaults:
            self.ensure_system_bases(principal)
        get_by_code = getattr(self.bases, "get_by_code", None)
        if not callable(get_by_code):
            return None
        mandatory = get_by_code(MANDATORY_BASE_CODE)
        try:
            default_user = get_by_code(
                _default_user_base_code_for_principal(principal),
                owner_user_id=_owner_key_for_principal(principal),
            )
        except TypeError:
            default_user = get_by_code(_default_user_base_code_for_principal(principal))
        if default_user is not None and not self._is_base_accessible(default_user, principal):
            default_user = None
        selection = self.selections.get_for_scope(_selection_scope_for_principal(principal))
        selected_base = (
            selection.selected_knowledge_base
            if selection
            and selection.selected_knowledge_base
            and self._is_base_accessible(selection.selected_knowledge_base, principal)
            else None
        )
        if mandatory is None and default_user is None and selected_base is None:
            return None
        selected_user_base = selected_base or default_user or mandatory
        if selected_user_base is None:
            return None
        use_user_base = selected_user_base.kind == KnowledgeBaseKind.USER_MANAGED
        use_mandatory_base = selected_user_base.kind == KnowledgeBaseKind.SYSTEM_MANDATORY
        mandatory_base = selected_user_base if use_mandatory_base else mandatory
        mandatory_version = (
            self.versions.get_active(
                knowledge_base_id=selected_user_base.knowledge_base_id, eager=True
            )
            if use_mandatory_base
            else None
        )
        selected_user_version: KnowledgeVersion | None = None
        if use_user_base and selection and selection.selected_knowledge_version_id:
            candidate_version = self.versions.get_with_documents(
                selection.selected_knowledge_version_id
            )
            if (
                candidate_version is not None
                and str(candidate_version.knowledge_base_id)
                == str(selected_user_base.knowledge_base_id)
                and is_generation_selectable_version(candidate_version)
            ):
                selected_user_version = candidate_version
        if use_user_base and selected_user_version is None:
            active_version = self.versions.get_active(
                knowledge_base_id=selected_user_base.knowledge_base_id, eager=True
            )
            if active_version is not None and is_generation_selectable_version(active_version):
                selected_user_version = active_version
        return EffectiveKnowledgeScope(
            mandatory_base=mandatory_base,
            mandatory_version=mandatory_version,
            selected_user_base=selected_user_base,
            selected_user_version=selected_user_version,
        )

    def get_existing_effective_scope(
        self, principal: AuthPrincipal | None = None
    ) -> EffectiveKnowledgeScope | None:
        return self._resolve_effective_scope(principal, ensure_defaults=False)

    def get_effective_scope(
        self, principal: AuthPrincipal | None = None
    ) -> EffectiveKnowledgeScope:
        scope = self._resolve_effective_scope(principal, ensure_defaults=True)
        if scope is None:
            raise NotFoundError("KnowledgeScope", _selection_scope_for_principal(principal))
        return scope


def _serialize_base(base: KnowledgeBase | None) -> dict[str, Any] | None:
    if base is None:
        return None
    return {
        "knowledge_base_id": str(base.knowledge_base_id),
        "code": base.code,
        "name": base.name,
        "description": base.description,
        "kind": getattr(base.kind, "value", base.kind),
        "status": getattr(base.status, "value", base.status),
        "owner_user_id": getattr(base, "owner_user_id", None),
        "created_at": base.created_at,
        "updated_at": base.updated_at,
    }


def _serialize_version(version: KnowledgeVersion | None) -> dict[str, Any] | None:
    if version is None:
        return None
    return {
        "knowledge_version_id": str(version.knowledge_version_id),
        "knowledge_base_id": str(version.knowledge_base_id),
        "version_no": version.version_no,
        "status": getattr(version.status, "value", version.status),
        "created_at": version.created_at,
        "activated_at": version.activated_at,
    }
