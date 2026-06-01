from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.db.enums import Criticality, DocumentType


@dataclass(frozen=True, slots=True)
class BasisRequirement:
    role_code: str
    display_name: str
    match_tokens: tuple[str, ...]
    document_types: tuple[DocumentType, ...]
    required: bool = True


REQUIRED_BASIS_REQUIREMENTS: tuple[BasisRequirement, ...] = (
    BasisRequirement(
        role_code="ig1242_oda_component_inventory",
        display_name="IG1242 / ODA Component Inventory",
        match_tokens=("ig1242", "oda component inventory", "component inventory"),
        document_types=(DocumentType.NORMATIVE, DocumentType.ARCHITECTURE),
        required=True,
    ),
    BasisRequirement(
        role_code="oda",
        display_name="ODA Core Principles",
        match_tokens=("oda core", "core principles", "оператор деятельност"),
        document_types=(DocumentType.NORMATIVE,),
        required=True,
    ),
    BasisRequirement(
        role_code="archimate_3_2",
        display_name="ArchiMate 3.2",
        match_tokens=("archimate 3.2", "archimate", "моделир", "modelling rules"),
        document_types=(DocumentType.ARCHITECTURE,),
        required=True,
    ),
    BasisRequirement(
        role_code="technology_standard",
        display_name="Selected Technology Standard",
        match_tokens=(
            "technology standard",
            "techstd",
            "selected technology standard",
            "technology",
            "технолог",
            "операцион",
            "ubuntu",
            "linux",
            "windows server",
        ),
        document_types=(DocumentType.NORMATIVE, DocumentType.TECHNOLOGY, DocumentType.OTHER),
        required=True,
    ),
)

REFERENCE_BASIS_REQUIREMENTS: tuple[BasisRequirement, ...] = (
    BasisRequirement(
        role_code="template_or_principles",
        display_name="Templates / Architecture Principles",
        match_tokens=(
            "template",
            "templates",
            "principle",
            "principles",
            "corporate",
            "architecture principles",
        ),
        document_types=(DocumentType.ARCHITECTURE, DocumentType.NORMATIVE),
        required=False,
    ),
)

ALL_BASIS_REQUIREMENTS: tuple[BasisRequirement, ...] = (
    REQUIRED_BASIS_REQUIREMENTS + REFERENCE_BASIS_REQUIREMENTS
)
KNOWN_BASIS_ROLE_CODES: frozenset[str] = frozenset(
    requirement.role_code for requirement in ALL_BASIS_REQUIREMENTS
)
REFERENCE_ONLY_ROLE_CODE = "reference_only"
_BUNDLE_ROLE_CODE_METADATA_KEY = "bundle_role_code"
_BUNDLE_REQUIRED_FLAG_METADATA_KEY = "bundle_required_flag"


@dataclass(frozen=True, slots=True)
class BasisDocumentDescriptor:
    document_id: str | None
    title: str
    role_code: str
    version_ref: str | None
    required_flag: bool
    document_type: str | None = None


@dataclass(frozen=True, slots=True)
class BasisInventory:
    basis_documents: list[BasisDocumentDescriptor]
    required_packages: list[dict[str, Any]]
    missing_required_packages: list[str]
    required_basis_present: bool
    optional_reference_present: bool


def _document_value(document: Any, field: str) -> Any:
    return getattr(document, field, None)


def _version_document_value(item: Any, field: str) -> Any:
    return getattr(item, field, None) if item is not None else None


def _document_type_value(document: Any) -> DocumentType | None:
    raw = _document_value(document, "document_type")
    if isinstance(raw, DocumentType):
        return raw
    if raw is None:
        return None
    try:
        return DocumentType(str(getattr(raw, "value", raw)))
    except Exception:
        return None


def _source_criticality_value(document: Any) -> str | None:
    source = getattr(document, "source", None)
    raw = getattr(source, "criticality", None)
    if isinstance(raw, Criticality):
        return raw.value
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


def normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def classify_basis_requirement(document: Any) -> BasisRequirement | None:
    title = normalize_text(_document_value(document, "title"))
    uri = normalize_text(_document_value(document, "uri"))
    version_label = normalize_text(_document_value(document, "version_label"))
    haystack = " ".join(part for part in (title, uri, version_label) if part)
    document_type = _document_type_value(document)

    for requirement in ALL_BASIS_REQUIREMENTS:
        if (
            document_type is not None
            and requirement.document_types
            and document_type not in requirement.document_types
        ):
            continue
        if any(token in haystack for token in requirement.match_tokens):
            return requirement
    return None


def resolve_basis_assignment(item: Any) -> tuple[str, bool]:
    document = getattr(item, "document", item)
    explicit_role_code = _version_document_value(item, "role_code")
    explicit_required_flag = _version_document_value(item, "required_flag")

    if explicit_role_code:
        role_code = str(explicit_role_code)
        required_flag = bool(explicit_required_flag)
        if role_code == REFERENCE_ONLY_ROLE_CODE:
            return role_code, False
        return role_code, required_flag

    document_metadata = dict(getattr(document, "document_metadata", None) or {})
    metadata_role_code = document_metadata.get(_BUNDLE_ROLE_CODE_METADATA_KEY)
    if metadata_role_code:
        role_code = str(metadata_role_code)
        required_flag = bool(document_metadata.get(_BUNDLE_REQUIRED_FLAG_METADATA_KEY, False))
        if role_code == REFERENCE_ONLY_ROLE_CODE:
            return role_code, False
        return role_code, required_flag

    requirement = classify_basis_requirement(document)
    if requirement is None:
        return REFERENCE_ONLY_ROLE_CODE, False
    if requirement.required:
        return requirement.role_code, True
    return requirement.role_code, _source_criticality_value(document) == Criticality.REQUIRED.value


def build_basis_inventory(items: Iterable[Any]) -> BasisInventory:
    descriptors: list[BasisDocumentDescriptor] = []
    matched_roles: set[str] = set()

    for item in items:
        if item is None:
            continue
        document = getattr(item, "document", item)
        role_code, required_flag = resolve_basis_assignment(item)
        if role_code not in KNOWN_BASIS_ROLE_CODES:
            continue
        matched_roles.add(role_code)
        descriptors.append(
            BasisDocumentDescriptor(
                document_id=str(_document_value(document, "document_id"))
                if _document_value(document, "document_id")
                else None,
                title=_document_value(document, "title") or "Документ без названия",
                role_code=role_code,
                version_ref=_document_value(document, "version_label"),
                required_flag=required_flag,
                document_type=getattr(
                    _document_type_value(document), "value", _document_type_value(document)
                ),
            )
        )

    required_packages: list[dict[str, Any]] = []
    missing_required_packages: list[str] = []
    for requirement in REQUIRED_BASIS_REQUIREMENTS:
        present = requirement.role_code in matched_roles
        required_packages.append(
            {
                "role_code": requirement.role_code,
                "display_name": requirement.display_name,
                "required": True,
                "present": present,
            }
        )
        if not present:
            missing_required_packages.append(requirement.role_code)

    optional_reference_present = any(
        req.role_code in matched_roles for req in REFERENCE_BASIS_REQUIREMENTS
    )
    return BasisInventory(
        basis_documents=descriptors,
        required_packages=required_packages,
        missing_required_packages=missing_required_packages,
        required_basis_present=not missing_required_packages,
        optional_reference_present=optional_reference_present,
    )


def build_basis_inventory_for_version_documents(version_documents: Iterable[Any]) -> BasisInventory:
    return build_basis_inventory(version_documents)
