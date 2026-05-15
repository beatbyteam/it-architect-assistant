from __future__ import annotations

from enum import StrEnum


class AccountType(StrEnum):
    HUMAN = "human"
    SERVICE = "service"


class SourceType(StrEnum):
    REPOSITORY = "repository"
    URL_LIST = "url_list"
    MANUAL_UPLOAD = "manual_upload"
    URL = "url"
    LOCAL_FOLDER = "local_folder"
    CATALOG = "catalog"
    MANUAL_REGISTRY = "manual_registry"


class KnowledgeBaseKind(StrEnum):
    SYSTEM_MANDATORY = "system_mandatory"
    USER_MANAGED = "user_managed"


class KnowledgeBaseStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class Criticality(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class SourceStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class SourceSyncMode(StrEnum):
    FULL_SCAN = "full_scan"
    LINK_DISCOVERY = "link_discovery"


class DocumentType(StrEnum):
    NORMATIVE = "normative"
    ARCHITECTURE = "architecture"
    API = "api"
    TECHNOLOGY = "technology"
    OTHER = "other"


class SourceDocumentStatus(StrEnum):
    REGISTERED = "registered"
    FETCHED = "fetched"
    PARSED = "parsed"
    FAILED = "failed"
    ARCHIVED = "archived"


class SourceScope(StrEnum):
    ALL = "all"
    SELECTED = "selected"


class UpdateRunType(StrEnum):
    MANUAL = "manual"
    IMPORT = "import"
    SCHEDULED_SYNC = "scheduled_sync"
    UPLOAD = "upload"
    DELETE = "delete"
    REBUILD = "rebuild"


class KnowledgeUpdateStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    LOADING = "loading"
    PARSING = "parsing"
    EXTRACTING = "extracting"
    INDEXING = "indexing"
    VALIDATING = "validating"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELED = "canceled"


class SourceProcessingStatus(StrEnum):
    QUEUED = "queued"
    DISCOVERED = "discovered"
    FETCHED = "fetched"
    PARSED = "parsed"
    EXTRACTED = "extracted"
    REUSED = "reused"
    SKIPPED = "skipped"
    FAILED = "failed"


class KnowledgeVersionStatus(StrEnum):
    DRAFT = "draft"
    PREPARING = "preparing"
    LOADED = "loaded"
    INDEXED = "indexed"
    VALIDATING = "validating"
    VALIDATED = "validated"
    ACTIVE = "active"
    ARCHIVED = "archived"
    FAILED = "failed"
    REJECTED = "rejected"


class FragmentType(StrEnum):
    REQUIREMENT = "requirement"
    RULE = "rule"
    PATTERN = "pattern"
    COMPONENT = "component"
    INTEGRATION = "integration"
    API = "api"
    GLOSSARY = "glossary"
    OTHER = "other"


class FragmentStatus(StrEnum):
    ACTIVE = "active"
    EXCLUDED = "excluded"


class ExtractedKnowledgeType(StrEnum):
    SUMMARY = "summary"
    NORMATIVE_RULE = "normative_rule"
    ARCHITECTURAL_PRINCIPLE = "architectural_principle"
    CONSTRAINT = "constraint"
    MANDATORY_REQUIREMENT = "mandatory_requirement"
    ENTITY = "entity"
    ENTITY_RELATION = "entity_relation"
    INTEGRATION_REQUIREMENT = "integration_requirement"
    TECHNOLOGY_STANDARD = "technology_standard"
    TERM = "term"
    RISK = "risk"


class ExtractionQualityStatus(StrEnum):
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"


class DocumentDeltaKind(StrEnum):
    NEW = "new"
    CHANGED = "changed"
    DELETED = "deleted"
    UNCHANGED = "unchanged"


class RuleCategory(StrEnum):
    ARCHITECTURE = "architecture"
    COMPONENT = "component"
    API = "api"
    INTEGRATION = "integration"
    NOTATION = "notation"
    TECHNOLOGY = "technology"
    GOVERNANCE = "governance"


class Severity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MEDIUM = "major"
    MINOR = "minor"
    INFO = "info"


class NormativeRuleStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXCLUDED = "excluded"


class BusinessTaskStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    NEEDS_CLARIFICATION = "needs_clarification"
    REQUIRES_CLARIFICATION = "needs_clarification"
    CLARIFIED = "clarified"
    READY_FOR_GENERATION = "ready_for_generation"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"


class ClarificationRequestStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    CLOSED = "closed"
    SUPERSEDED = "superseded"
    CANCELED = "canceled"


class GenerationRunStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class SolutionVersionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class SolutionListItemGroup(StrEnum):
    ASSUMPTION = "assumption"
    NEXT_STEP = "next_step"


class VerificationRunStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class ProtocolSummaryStatus(StrEnum):
    PASSED = "passed"
    PASSED_WITH_COMMENTS = "passed_with_comments"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class VerificationProtocolStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    INCOMPLETE = "incomplete"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class CheckResultStatus(StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    NOT_DETERMINED = "not_determined"


class AuditSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


ROLE_USER = "USER"
ROLE_ADMIN = "ADMIN"
ROLE_MVP_ADMIN = "MVP_ADMIN"
MVP_ROLE_CODES = [ROLE_USER, ROLE_ADMIN, ROLE_MVP_ADMIN]
MVP_USER_ROLE_CODES = frozenset({ROLE_USER, ROLE_ADMIN, ROLE_MVP_ADMIN})


def normalize_role_code(role_code: str) -> str:
    return role_code.strip().upper()
