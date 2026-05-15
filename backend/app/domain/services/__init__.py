from __future__ import annotations

from importlib import import_module

__all__ = [
    "AuthLiteService",
    "BusinessTaskService",
    "GenerationRunService",
    "HealthService",
    "KnowledgeSourceService",
    "KnowledgeUpdateService",
    "KnowledgeVersionService",
    "OperationsQueryService",
    "SolutionQueryService",
    "VerificationQueryService",
    "VerificationRunService",
]

_MODULE_MAP = {
    "AuthLiteService": ("app.domain.services.auth", "AuthLiteService"),
    "BusinessTaskService": ("app.domain.services.generation", "BusinessTaskService"),
    "GenerationRunService": ("app.domain.services.generation", "GenerationRunService"),
    "SolutionQueryService": ("app.domain.services.generation", "SolutionQueryService"),
    "HealthService": ("app.domain.services.health", "HealthService"),
    "KnowledgeSourceService": ("app.domain.services.knowledge", "KnowledgeSourceService"),
    "KnowledgeUpdateService": ("app.domain.services.knowledge", "KnowledgeUpdateService"),
    "KnowledgeVersionService": ("app.domain.services.knowledge", "KnowledgeVersionService"),
    "OperationsQueryService": ("app.domain.services.operations", "OperationsQueryService"),
    "VerificationQueryService": ("app.domain.services.verification", "VerificationQueryService"),
    "VerificationRunService": ("app.domain.services.verification", "VerificationRunService"),
}


def __getattr__(name: str):
    if name not in _MODULE_MAP:
        raise AttributeError(name)
    module_name, attr_name = _MODULE_MAP[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
