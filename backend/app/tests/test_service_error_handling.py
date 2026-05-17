from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.exceptions import NotFoundError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    CheckResultStatus,
    Criticality,
    DocumentType,
    KnowledgeVersionStatus,
    Severity,
    SourceDocumentStatus,
    SourceStatus,
)
from app.domain.services.generation.post_validation import GenerationPostValidator
from app.domain.services.generation.run_service import GenerationRunService
from app.domain.services.generation.runtime import _run_validation_stage
from app.domain.services.knowledge.source_service import KnowledgeSourceService
from app.domain.services.knowledge.update_service import KnowledgeUpdateService
from app.domain.services.knowledge_bases import KnowledgeBaseService
from app.domain.services.canonical_read_helpers import build_protocol_explainability
from app.domain.services import mvp_protocol_read_service as protocol_read_module
from app.domain.services.mvp_protocol_read_service import _materialize_basis_documents
from app.domain.services.mvp_task_write_service import _reassess_task
from app.domain.services.task_readiness import QUESTION_TEMPLATES, TaskReadinessPolicy
from app.domain.services.verification.common import VerificationExecutionContext
from app.domain.services.verification.rule_engine import VerificationRuleEngine
from app.domain.services.verification.rule_executors import (
    ConsistencyRulesExecutor,
    VerificationSupportContext,
)
from app.domain.services.verification.run_service import VerificationRunService
from app.domain.services.workflow_runtime import dispatch_run, should_execute_inline
from app.integrations.generation.contracts import GenerationRisk, GenerationSection
from app.integrations.generation.payload_normalization_sections import (
    _apply_section_guidance,
    _deduplicate_section_bodies,
)
from app.integrations.generation.payload_normalization_source_refs import (
    _enrich_critical_section_source_refs,
)
from app.integrations.generation.payload_normalization_validation import (
    _validate_generation_solution_payload,
)
from app.integrations.verification import VerificationRuleDefinition


class _ExplodingExecutor:
    def execute(self, *, rule, context, support):
        raise ValueError("boom")


class _ProdLikeSettings:
    app_env = "production"

    @staticmethod
    def is_prod_like_env() -> bool:
        return True


class _DevSettings:
    app_env = "dev"

    @staticmethod
    def is_prod_like_env() -> bool:
        return False


def _principal() -> AuthPrincipal:
    return AuthPrincipal(
        user_id="user-1",
        login="architect",
        display_name="Architect",
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
    )


def test_should_execute_inline_blocks_all_prod_like_envs() -> None:
    assert should_execute_inline(_ProdLikeSettings(), True) is False
    assert should_execute_inline(_DevSettings(), True) is True
    assert should_execute_inline(SimpleNamespace(app_env="release"), True) is False
    assert should_execute_inline(SimpleNamespace(app_env="production"), True) is False


def test_dispatch_run_uses_queue_failure_handler() -> None:
    result = dispatch_run(
        settings=_ProdLikeSettings(),
        requested_inline=False,
        inline_executor=lambda: "inline",
        queue_dispatcher=lambda: (_ for _ in ()).throw(RuntimeError("broker down")),
        queue_failure_handler=lambda exc: f"handled:{exc}",
    )

    assert result == "handled:broker down"


def test_verification_rule_engine_raises_on_executor_failure() -> None:
    engine = VerificationRuleEngine(executors={"technical": _ExplodingExecutor()})
    context = VerificationExecutionContext(
        solution=SimpleNamespace(
            sections=[],
            list_items=[],
            components=[],
            integrations=[],
            risks=[],
            executive_summary="Summary",
            generation_run=None,
        ),
        run=SimpleNamespace(knowledge_version=SimpleNamespace(version_documents=[])),
        rules=[
            VerificationRuleDefinition(
                "VR-TEC-01", "Synthetic rule", "technical", Severity.CRITICAL, technical=True
            )
        ],
        rule_lookup={},
    )

    with pytest.raises(RuntimeError, match="VR-TEC-01"):
        engine.execute(context)


def test_materialize_basis_documents_is_read_only() -> None:
    service = SimpleNamespace(session=Mock())
    protocol = SimpleNamespace(
        verification_protocol_id="protocol-1",
        verification_run=SimpleNamespace(
            knowledge_version=SimpleNamespace(
                version_documents=[
                    SimpleNamespace(
                        role_code="template_or_principles",
                        required_flag=True,
                        document=SimpleNamespace(
                            document_id="doc-1",
                            title="Architecture baseline",
                            version_label="v1",
                            uri="file:///baseline.md",
                            document_type=DocumentType.ARCHITECTURE,
                            source=SimpleNamespace(criticality=Criticality.REQUIRED),
                        ),
                    )
                ]
            )
        ),
    )

    items = _materialize_basis_documents(service, protocol)

    assert len(items) == 1
    assert items[0].title == "Architecture baseline"
    service.session.add.assert_not_called()
    service.session.flush.assert_not_called()
    service.session.commit.assert_not_called()


def test_verification_protocol_rendered_payload_reuses_internal_payload_helper(
    monkeypatch,
) -> None:
    def fake_payload(service, protocol_id, principal, *, verification_query_service_factory):
        assert protocol_id == "protocol-1"
        assert verification_query_service_factory is _VerificationQuery
        return {"basis_documents": [{"title": "Architecture baseline"}]}

    class _VerificationQuery:
        def __init__(self, session) -> None:
            self.session = session

        def get_protocol_view(self, protocol_id, principal):
            return {
                "verification_protocol_id": protocol_id,
                "issued_at": "2026-05-16T00:00:00+00:00",
                "summary_status": "passed",
                "protocol_status": "published",
                "rendered_html": "<h1>Протокол проверки</h1>",
                "publication_artifact_id": "artifact-1",
                "publication_revision_no": 1,
                "artifact_state": "published",
                "version_hash": "hash-1",
            }

        def get_protocol(self, protocol_id, principal):
            return SimpleNamespace(
                verification_protocol_id=protocol_id,
                verification_run=SimpleNamespace(scope_snapshot={"mode": "full"}),
            )

    monkeypatch.setattr(protocol_read_module, "get_verification_protocol_payload", fake_payload)
    service = SimpleNamespace(
        session=Mock(),
        get_verification_protocol_payload=Mock(side_effect=AssertionError("wrong helper")),
        map_protocol_state=lambda status, summary: "published",
        _list_publication_revisions=lambda **kwargs: [],
        _build_snapshot_summary=lambda snapshot: {"mode": snapshot["mode"]},
        _build_protocol_explainability=lambda protocol, basis_documents: {
            "basis_count": len(basis_documents)
        },
    )

    payload = protocol_read_module.get_verification_protocol_rendered_payload(
        service,
        "protocol-1",
        _principal(),
        verification_query_service_factory=_VerificationQuery,
    )

    assert payload["rendered_html"] == "<h1>Протокол проверки</h1>"
    assert payload["protocol_state"] == "published"
    assert payload["snapshot_summary"] == {"mode": "full"}
    assert payload["explainability"] == {"basis_count": 1}
    service.get_verification_protocol_payload.assert_not_called()


def test_protocol_explainability_accepts_check_results_without_diagnostics() -> None:
    protocol = SimpleNamespace(
        verification_run=SimpleNamespace(diagnostics={}, scope_snapshot={}),
        check_results=[
            SimpleNamespace(
                sort_order=1,
                evidence_ref=None,
                related_section_ref=None,
                rule_name="Проверка структуры",
                check_name="Проверка структуры",
                status="failed",
            )
        ],
    )

    payload = build_protocol_explainability(protocol, basis_documents=[])

    assert payload["evidence_coverage"]["findings_without_evidence"] == [
        "Проверка структуры"
    ]


def test_knowledge_base_read_methods_do_not_commit_when_defaults_are_missing() -> None:
    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.session = Mock()
    service.bases = SimpleNamespace(
        get_by_code=lambda code: None,
        get=lambda knowledge_base_id: None,
        list_visible=lambda: [],
    )
    service.selections = SimpleNamespace(get_for_scope=lambda scope: None)
    service.versions = SimpleNamespace(
        get=lambda knowledge_version_id: None, get_active=lambda **kwargs: None
    )

    with pytest.raises(NotFoundError):
        service.get_default_user_base()
    with pytest.raises(NotFoundError):
        service.get_base("kb-missing")
    assert service.list_payloads() == []
    service.session.commit.assert_not_called()


def test_remove_document_and_start_update_rolls_back_when_update_cannot_start(monkeypatch) -> None:
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    service.session = Mock()
    service.audit = Mock()
    document = SimpleNamespace(
        document_id="doc-1",
        source_id="source-1",
        title="Reference",
        status=SourceDocumentStatus.FETCHED,
        is_latest=True,
    )
    source = SimpleNamespace(
        source_id="source-1", knowledge_base_id="kb-1", status=SourceStatus.ACTIVE
    )
    service.get_document = lambda document_id: document
    service._assert_document_mutable = lambda *args, **kwargs: None
    service.get_source = lambda source_id: source

    class _FailingUpdater:
        def __init__(self, session, settings) -> None:
            self.session = session
            self.settings = settings

        def start_run(self, payload, principal):
            raise RuntimeError("queue down")

    import app.domain.services.knowledge.source_service as module

    monkeypatch.setattr(module, "KnowledgeUpdateService", _FailingUpdater)

    with pytest.raises(RuntimeError, match="queue down"):
        service.remove_document_and_start_update(
            "doc-1",
            _principal(),
            settings=SimpleNamespace(),
            execute_inline=False,
        )

    service.session.flush.assert_called_once()
    service.session.rollback.assert_called_once()
    service.session.commit.assert_not_called()


def test_generation_run_stage_title_is_callable_on_instance() -> None:
    service = GenerationRunService.__new__(GenerationRunService)

    assert service._stage_title("queued") == "Поставлено в очередь"


def test_generation_validation_stage_returns_expected_runtime_contract() -> None:
    payload = SimpleNamespace(assumptions=[], next_steps=[], section_readiness=[])
    validation_summary = {"groundedness_score": 0.9, "citation_coverage": 0.8}
    service = SimpleNamespace(
        session=Mock(),
        validator=SimpleNamespace(validate=Mock(return_value=validation_summary)),
        llm_gateway=SimpleNamespace(last_call_diagnostics={"fallback_used": False}),
        _record_operation_step=Mock(),
        _with_stage_history=Mock(side_effect=lambda diagnostics, *args, **kwargs: diagnostics),
    )
    run = SimpleNamespace(
        status=SimpleNamespace(value="running"),
        diagnostics={},
        current_stage=None,
    )
    retrieval = SimpleNamespace(fragments=[])

    result = _run_validation_stage(
        service,
        run=run,
        retrieval=retrieval,
        coverage_summary={"required_role_coverage": {"required": 1}},
        payload=payload,
        stage_metrics={},
    )

    assert len(result) == 3
    returned_validation_summary, quality_outcomes, explainability = result
    assert returned_validation_summary == validation_summary
    assert quality_outcomes["schema_valid"] is True
    assert explainability["assumptions"] == []


def test_generation_risk_limitation_alias_is_normalized() -> None:
    risk = GenerationRisk.model_validate(
        {
            "limitation": "Integration contracts are not confirmed before solution approval.",
            "severity": "major",
        }
    )

    assert risk.title == "Integration contracts are not confirmed before solution approval."
    assert risk.description == "Integration contracts are not confirmed before solution approval."
    assert risk.severity == Severity.MAJOR


def test_generation_component_boundaries_are_inferred_from_archimate_semantics() -> None:
    payload = _validate_generation_solution_payload(
        {
            "solution_title": "Сервис согласования архитектурных артефактов",
            "executive_summary": "Решение согласует и публикует архитектурные артефакты.",
            "sections": [
                {
                    "section_code": code,
                    "title": code,
                    "body_markdown": "Раздел требует нормализации объектов управления ArchiMate 3.2.",
                    "source_refs": [],
                }
                for code in [
                    "general_information",
                    "business_tasks_description",
                    "it_architecture_content",
                    "business_architecture",
                    "data_architecture",
                    "application_architecture",
                    "technology_architecture",
                    "additional_information",
                ]
            ],
            "components": [
                {
                    "component_name": "Технический специалист",
                    "role_description": "Компонент Технический специалист участвует в реализации целевой архитектуры и требует дальнейшей детализации обязанностей.",
                    "boundary_type": "application_architecture",
                },
                {
                    "component_name": "Метаданные о документах и модели данных документов",
                    "role_description": "Компонент хранит сведения об артефактах.",
                    "boundary_type": "application_architecture",
                },
                {
                    "component_name": "API PostgreSQL и Redis для управления очередями задач",
                    "role_description": "Компонент участвует в реализации целевой архитектуры.",
                    "boundary_type": "application_architecture",
                },
                {
                    "component_name": "Серверное приложение для согласования документов",
                    "role_description": "Компонент участвует в реализации целевой архитектуры.",
                    "boundary_type": "application_architecture",
                },
                {
                    "component_name": "Обработка и утверждение архитектурных документов",
                    "role_description": "Компонент участвует в реализации целевой архитектуры.",
                    "boundary_type": "application_architecture",
                },
                {
                    "component_name": "Участник системы",
                    "role_description": "Business Service Участник системы описывает бизнес-услугу целевого сценария согласования архитектурных артефактов.",
                    "boundary_type": "business_architecture",
                },
                {
                    "component_name": "Создание и отправка артефактов",
                    "role_description": "Business Service Создание и отправка артефактов описывает бизнес-услугу целевого сценария согласования архитектурных артефактов.",
                    "boundary_type": "business_architecture",
                },
                {
                    "component_name": "Интересующую компанию представляют роль **Архитектор IT**. Основная функция",
                    "role_description": "Участвует в согласовании архитектурных документов.",
                    "boundary_type": "business_architecture",
                },
                {
                    "component_name": "Solution Core",
                    "role_description": "Сводное описание решения, не являющееся объектом управления ArchiMate.",
                    "boundary_type": "business_architecture",
                },
                {
                    "component_name": "Облачное хранилище документов: Amazon S3 (Artifact)",
                    "role_description": "Облачное хранилище для хранения данных документов.",
                    "boundary_type": "technology_architecture",
                },
            ],
            "assumptions": ["Решение работает во внутреннем корпоративном контуре."],
            "next_steps": ["Согласовать границы и контракты."],
            "risks": ["Не подтверждены интеграционные контракты."],
        }
    )

    boundaries = {item.component_name: item.boundary_type for item in payload.components}
    assert boundaries["Технический специалист"] == "business_architecture"
    assert (
        boundaries["Метаданные о документах и модели данных документов"]
        == "data_architecture"
    )
    technology_name = next(
        name for name in boundaries if name.startswith("API корпоративное хранилище данных")
    )
    assert boundaries[technology_name] == "technology_architecture"
    assert "PostgreSQL" not in technology_name
    assert "Redis" not in technology_name
    assert (
        boundaries["Серверное приложение для согласования документов"]
        == "application_architecture"
    )
    assert (
        boundaries["Обработка и утверждение архитектурных документов"]
        == "business_architecture"
    )
    role_descriptions = {
        item.component_name: item.role_description for item in payload.components
    }
    assert role_descriptions["Участник системы"].startswith("Business Role ")
    assert role_descriptions["Создание и отправка артефактов"].startswith(
        "Business Process "
    )
    assert "Архитектор IT" in boundaries
    assert boundaries["Архитектор IT"] == "business_architecture"
    assert role_descriptions["Архитектор IT"].startswith("Business Role ")
    assert "Solution Core" not in boundaries
    sanitized_storage_name = next(
        name for name in boundaries if "корпоративное хранилище" in name.casefold()
    )
    assert "Amazon S3" not in sanitized_storage_name
    assert "облач" not in sanitized_storage_name.casefold()
    assert "облач" not in role_descriptions[sanitized_storage_name].casefold()


def test_section_guidance_deduplicates_repeated_section_bodies() -> None:
    repeated_body = (
        "Одинаковое тело секции описывает решение слишком общо и может быть возвращено "
        "локальной моделью для нескольких разделов."
    )
    sections = [
        GenerationSection.model_validate(
            {
                "section_code": code,
                "title": code,
                "body_markdown": repeated_body,
                "source_refs": [],
            }
        )
        for code in [
            "general_information",
            "business_tasks_description",
            "it_architecture_content",
            "business_architecture",
            "data_architecture",
            "application_architecture",
            "technology_architecture",
            "additional_information",
        ]
    ]

    patched_sections, deduplicated_codes = _deduplicate_section_bodies(
        sections,
        payload_context={"components": [], "integrations": []},
        task_title="Сервис согласования архитектурных артефактов",
        task_text="Нужно подготовить TOGAF-документ с объектами ArchiMate 3.2.",
        context_items=[],
        retrieved_fragments=[],
    )

    assert deduplicated_codes
    assert len({section.body_markdown for section in patched_sections}) == 8


def test_generation_normalization_builds_customer_requested_togaf_archimate_model() -> None:
    raw_payload = {
        "solution_title": "Архитектурное решение для сервиса согласования и публикации ИТ-архитектурных артефактов",
        "executive_summary": (
            "Решение представляет собой централизованный сервис для создания, согласования, "
            "хранения и публикации ИТ-архитектурных артефактов. Оно повышает прозрачность "
            "согласования, сокращает время обработки и обеспечивает доступ к актуальным версиям документов."
        ),
        "sections": [
            {
                "section_code": "general_information",
                "title": "Общие сведения",
                "body_markdown": "Централизованный сервис нужен для внутреннего корпоративного контура согласования.",
                "source_refs": [],
            },
            {
                "section_code": "business_tasks_description",
                "title": "Описание бизнес-задач",
                "body_markdown": "Нужно загружать архитектурные документы, отслеживать статус и публиковать итоговые версии за несколько секунд и достичь единого резерва данных.",
                "source_refs": [],
            },
            {
                "section_code": "it_architecture_content",
                "title": "Содержание ИТ-архитектуры",
                "body_markdown": "Решение будет состоять из пяти слоев: бизнес-, данных, прикладного и технологического.",
                "source_refs": [],
            },
            {
                "section_code": "business_architecture",
                "title": "Бизнес-архитектура",
                "body_markdown": "### Роли и бизнес-процессы: пользователь регистрирует аккаунт, загружает артефакты и получает статус.",
                "source_refs": [],
            },
            {
                "section_code": "data_architecture",
                "title": "Архитектура данных",
                "body_markdown": "### Данные: В артикуле находятся артефакты, замечания экспертов, история изменений. Источники dữ liệu: внутренние системы. Проще всего хранить данные как репликасы в облачном хранилище и корпоративном ИТ-ландшаftом. Документы передаются через **Business Interface** и **Service Document Processing**.",
                "source_refs": [],
            },
            {
                "section_code": "application_architecture",
                "title": "Архитектура приложений",
                "body_markdown": "Нагрузочный тестовый процесс осуществляет проверки согласования артефактов.",
                "source_refs": [],
            },
            {
                "section_code": "technology_architecture",
                "title": "Технологическая архитектура",
                "body_markdown": "### Уровни инфраструктуры: Node A Linux, Node B Windows, Node C Ubuntu, БД и кэширование. Сокрываются другие специфические детали технологического слоя. Облачное хранилище документов: Amazon S3.",
                "source_refs": [],
            },
            {
                "section_code": "additional_information",
                "title": "Дополнительные сведения",
                "body_markdown": "Ограничения, допущения, риски и открытые вопросы уточняются до утверждения готовности решения.",
                "source_refs": [],
            },
        ],
        "assumptions": [
            "Решение разворачивается во внутреннем корпоративном контуре и не требует обязательной зависимости от внешних облачных сервисов."
        ],
        "next_steps": [
            "Согласовать API-контракты, роли участников, модель данных, требования к хранению и эксплуатационные критерии приемки."
        ],
        "risks": [
            {
                "title": "Интеграционные зависимости могут задержать поставку",
                "severity": "major",
                "description": "Доступы к SSO, уведомлениям и корпоративным хранилищам могут задержать проверку целевого процесса согласования.",
                "mitigation": "Владелец интеграций согласует ответственных и тестовые контуры на архитектурном ревью; при блокировке используется согласованная заглушка и откат к ручной проверке.",
            }
        ],
    }

    payload = _validate_generation_solution_payload(raw_payload)
    patched_payload, diagnostics = _apply_section_guidance(
        payload,
        task_title="Сервис согласования ИТ-архитектурных артефактов",
        task_text=(
            "Нужно подготовить TOGAF-документ для сервиса согласования, хранения и "
            "публикации ИТ-архитектурных артефактов с объектами ArchiMate 3.2."
        ),
        context_items=[],
        retrieved_fragments=[],
    )
    validation_summary = GenerationPostValidator().validate(
        patched_payload,
        retrieved_fragments=[],
    )

    boundaries = {component.boundary_type for component in patched_payload.components}
    assert boundaries >= {
        "business_architecture",
        "data_architecture",
        "application_architecture",
        "technology_architecture",
    }
    assert patched_payload.integrations
    assert diagnostics["structured_model"]["entity_count"] >= len(patched_payload.components) + 8
    assert diagnostics["structured_model"]["relation_count"] == len(patched_payload.integrations)
    assert diagnostics["section_status_counts"] == {"ready": 8}
    assert validation_summary["structured_model_summary"]["entity_count"] > 0
    assert validation_summary["structured_model_summary"]["relation_count"] > 0
    technology_body = next(
        section.body_markdown
        for section in patched_payload.sections
        if section.section_code == "technology_architecture"
    )
    assert "Node A" not in technology_body
    assert "Windows" not in technology_body
    assert "Network" in technology_body
    assert "Technology Interface" in technology_body
    data_body = next(
        section.body_markdown
        for section in patched_payload.sections
        if section.section_code == "data_architecture"
    )
    assert "облач" not in data_body.casefold()
    assert "в артикуле" not in data_body.casefold()
    assert "репликасы" not in data_body.casefold()
    assert "ландшаft" not in data_body.casefold()
    assert "Business Interface" not in data_body
    assert "Service Document Processing" not in data_body
    assert "сокрываются" not in technology_body.casefold()
    assert "Amazon S3" not in technology_body
    assert "облач" not in technology_body.casefold()
    business_tasks_body = next(
        section.body_markdown
        for section in patched_payload.sections
        if section.section_code == "business_tasks_description"
    )
    assert "несколько секунд" not in business_tasks_body.casefold()
    assert "единый резерв" not in business_tasks_body.casefold()
    content_body = next(
        section.body_markdown
        for section in patched_payload.sections
        if section.section_code == "it_architecture_content"
    )
    assert "пяти слоев" not in content_body.casefold()
    application_body = next(
        section.body_markdown
        for section in patched_payload.sections
        if section.section_code == "application_architecture"
    )
    assert "нагрузочный тестовый процесс" not in application_body.casefold()


def test_source_ref_enrichment_preserves_section_readiness_and_structured_model() -> None:
    payload = _validate_generation_solution_payload(
        {
            "solution_title": "Архитектурное решение для сервиса согласования и публикации ИТ-архитектурных артефактов",
            "executive_summary": (
                "Решение представляет собой централизованный сервис для создания, согласования, "
                "хранения и публикации ИТ-архитектурных артефактов внутри корпоративного контура."
            ),
            "sections": [
                {
                    "section_code": code,
                    "title": code.replace("_", " ").title(),
                    "body_markdown": "Application Component, Data Object, Node и Business Process описываются согласно разделу.",
                    "source_refs": [],
                }
                for code in [
                    "general_information",
                    "business_tasks_description",
                    "it_architecture_content",
                    "business_architecture",
                    "data_architecture",
                    "application_architecture",
                    "technology_architecture",
                    "additional_information",
                ]
            ],
            "components": [
                {
                    "component_name": "Сервис управления артефактами",
                    "role_description": "Application Component реализует согласование и публикацию.",
                    "boundary_type": "application_architecture",
                    "external_flag": False,
                    "interfaces": [],
                }
            ],
            "integrations": [],
            "assumptions": ["Решение работает во внутреннем корпоративном контуре."],
            "next_steps": ["Уточнить API-контракты и критерии приемки архитектуры."],
            "risks": [
                {
                    "title": "Интеграции требуют согласования",
                    "severity": "major",
                    "description": "Несогласованные интеграции могут задержать проверку решения.",
                    "mitigation": "Владелец интеграций фиксирует контракт на ревью; при блокировке используется заглушка и откат к ручной проверке.",
                }
            ],
        }
    )
    guided_payload, _diagnostics = _apply_section_guidance(
        payload,
        task_title="Сервис согласования артефактов",
        task_text="Нужно подготовить TOGAF-документ с ArchiMate 3.2 объектами.",
        context_items=[],
        retrieved_fragments=[],
    )

    enriched_payload = _enrich_critical_section_source_refs(
        guided_payload,
        retrieved_fragments=[],
    )

    assert len(enriched_payload.section_readiness) == 8
    assert enriched_payload.structured_model is not None
    assert enriched_payload.structured_model.entities


def test_verification_run_stage_title_is_callable_on_instance() -> None:
    service = VerificationRunService.__new__(VerificationRunService)

    assert service._stage_title("queued") == "Поставлено в очередь"


def test_auto_activate_candidate_version_uses_imported_service(monkeypatch) -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service.session = Mock()
    candidate = SimpleNamespace(
        status=KnowledgeVersionStatus.VALIDATED, knowledge_version_id="kv-1"
    )
    run = SimpleNamespace(
        scope={"reason": "validated", "auto_activate_if_validated": True},
        current_stage="validated",
        initiator_user_id="user-1",
    )

    class _FakeKnowledgeVersionService:
        def __init__(self, session) -> None:
            self.session = session

        def activate(self, knowledge_version_id, principal, *, reason, auto_commit):
            return {
                "knowledge_version_id": knowledge_version_id,
                "principal": principal,
                "reason": reason,
                "auto_commit": auto_commit,
            }

    import app.domain.services.knowledge.update_service as module

    monkeypatch.setattr(module, "KnowledgeVersionService", _FakeKnowledgeVersionService)

    result = service._auto_activate_candidate_version(candidate, run)

    assert result["knowledge_version_id"] == "kv-1"
    assert result["reason"] == "validated"
    assert result["auto_commit"] is False
    assert result["principal"].user_id == "user-1"


def test_reassess_task_uses_question_templates_fallback_without_name_errors() -> None:
    readiness_policy = SimpleNamespace(
        assess=lambda task: SimpleNamespace(
            as_dict=lambda: {
                "missing_inputs": ["goal", "context"],
            }
        )
    )
    session = Mock()
    open_request = SimpleNamespace(state="open", question_items=None)
    task = SimpleNamespace(
        task_metadata={},
        clarification_requests=[open_request],
        status=None,
        updated_at=None,
    )
    service = SimpleNamespace(
        readiness_policy=readiness_policy,
        session=session,
        _latest_open_clarification=lambda _current_task: open_request,
    )

    _reassess_task(service, task, _principal(), reopen=True)

    assert task.status.value == "needs_clarification"
    assert open_request.question_items == [
        {"question_code": "goal", "question_text": QUESTION_TEMPLATES["goal"], "required": True},
        {
            "question_code": "context",
            "question_text": QUESTION_TEMPLATES["context"],
            "required": True,
        },
    ]


def test_task_readiness_marks_goal_answer_without_effect_as_partial() -> None:
    policy = TaskReadinessPolicy()
    task = SimpleNamespace(
        task_text="Нужно подготовить архитектурное решение для нового процесса.",
        task_metadata={"clarification_answers": {"goal": "Ускорить обработку заявок"}},
    )

    assessment = policy.assess(task).as_dict()

    assert "goal" in assessment["missing_inputs"]
    assert assessment["answer_evaluations"]["goal"]["status"] == "partial"
    assert "бизнес-эффект" in assessment["question_items"][0]["question_text"]


def test_task_readiness_sends_long_generic_task_to_clarifications() -> None:
    policy = TaskReadinessPolicy()
    task = SimpleNamespace(
        task_text=(
            "Нужно подготовить архитектурное решение для новой системы обработки заявок. "
            "Решение должно быть хорошим, современным и удобным. Нужна архитектура, "
            "компонентная схема и описание интеграций, ограничения потом уточним."
        ),
        task_metadata={},
    )

    assessment = policy.assess(task).as_dict()

    assert assessment["ready"] is False
    assert assessment["missing_inputs"] == [
        "goal",
        "context",
        "constraints",
        "integrations",
        "expected_output",
        "nfr",
    ]
    assert assessment["signals"]["input_presence"]["goal"]["task_text_status"] == "insufficient"
    assert assessment["signals"]["input_presence"]["constraints"]["task_text_status"] == "partial"


def test_task_readiness_accepts_specific_freeform_task_without_clarification() -> None:
    policy = TaskReadinessPolicy()
    task = SimpleNamespace(
        task_text=(
            "Цель: сократить время обработки заявок на 30% и снизить ручные ошибки. "
            "Сейчас заявки ведутся вручную в CRM, часть статусов теряется при передаче. "
            "Ограничения: SLA не более 5 минут, SSO и соответствие 152-ФЗ обязательны. "
            "NFR: доступность 99.9%, мониторинг метрик, резервное копирование ежедневно. "
            "Интеграции: CRM и биллинг по REST API, события передаются через Kafka. "
            "Ожидаемый результат: high-level HLD для согласования с компонентной схемой."
        ),
        task_metadata={},
    )

    assessment = policy.assess(task).as_dict()

    assert assessment["ready"] is True
    assert assessment["missing_inputs"] == []
    assert all(item["present"] for item in assessment["signals"]["input_presence"].values())


def test_task_readiness_accepts_short_but_explicit_no_integration_answer() -> None:
    policy = TaskReadinessPolicy()
    task = SimpleNamespace(
        task_text="Нужно подготовить архитектурное решение для нового процесса.",
        task_metadata={"clarification_answers": {"integrations": "Интеграций нет"}},
    )

    assessment = policy.assess(task).as_dict()

    assert assessment["answer_evaluations"]["integrations"]["status"] == "ready"
    assert "integrations" not in assessment["missing_inputs"]


def test_task_readiness_rejects_gibberish_even_when_answer_is_long_enough() -> None:
    policy = TaskReadinessPolicy()
    task = SimpleNamespace(
        task_text="Нужно подготовить архитектурное решение для нового процесса.",
        task_metadata={
            "clarification_answers": {
                "goal": "абракадабра абракадабра абракадабра",
            }
        },
    )

    assessment = policy.assess(task).as_dict()

    assert assessment["answer_evaluations"]["goal"]["status"] == "insufficient"
    assert "goal" in assessment["missing_inputs"]


def test_consistency_rules_executor_handles_boundary_normalization_for_cross_layer_checks() -> None:
    executor = ConsistencyRulesExecutor()
    context = SimpleNamespace(solution=SimpleNamespace(), run=SimpleNamespace())
    support = VerificationSupportContext(
        section_by_code={
            "business_architecture": SimpleNamespace(
                body_markdown="Business capability uses Billing API"
            ),
            "application_architecture": SimpleNamespace(
                body_markdown="Billing API handles requests"
            ),
            "technology_architecture": SimpleNamespace(
                body_markdown="Kubernetes hosts Billing API"
            ),
        },
        section_codes={
            "business_architecture",
            "application_architecture",
            "technology_architecture",
        },
        combined_section_text="",
        assumptions=[],
        next_steps=[],
        components=[
            SimpleNamespace(
                component_name="Business capability", boundary_type="business_architecture"
            ),
            SimpleNamespace(component_name="Billing API", boundary_type="application_architecture"),
            SimpleNamespace(component_name="Kubernetes", boundary_type="technology_architecture"),
        ],
        integrations=[],
        risks=[],
        basis_inventory={},
        required_fragments_by_role={},
        support_summary={},
    )
    rule_cns_03 = VerificationRuleDefinition(
        "VR-CNS-03", "Cross-layer consistency", "consistency", Severity.MEDIUM
    )
    rule_cns_04 = VerificationRuleDefinition(
        "VR-CNS-04", "Technology linkage", "consistency", Severity.MEDIUM
    )

    cns_03 = executor.execute(rule=rule_cns_03, context=context, support=support)
    cns_04 = executor.execute(rule=rule_cns_04, context=context, support=support)

    assert cns_03.status == CheckResultStatus.PASSED
    assert cns_04.status == CheckResultStatus.PASSED
