# ruff: noqa: E501
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.integrations.knowledge.embedding import EmbeddingService
from app.integrations.knowledge.retrieval_policies import RetrievalPolicyRegistry
from app.integrations.knowledge.text_processing import CHUNKING_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class PolicyStackDescriptor:
    retrieval_policy_version: str
    embedding_provider: str
    embedding_model_version: str
    embedding_dimensions: int
    chunking_policy_version: str
    reranker_provider: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_policy_stack(
    *, use_case: str, embeddings: EmbeddingService, reranker_provider: str = "heuristic"
) -> PolicyStackDescriptor:
    policy = RetrievalPolicyRegistry.get(use_case)
    descriptor = embeddings.describe()
    dimensions = descriptor.get("dimensions")
    return PolicyStackDescriptor(
        retrieval_policy_version=policy.policy_id,
        embedding_provider=str(descriptor["provider_name"]),
        embedding_model_version=str(descriptor["model_id"]),
        embedding_dimensions=(
            dimensions if isinstance(dimensions, int) else int(str(dimensions or 0))
        ),
        chunking_policy_version=CHUNKING_POLICY_VERSION,
        reranker_provider=reranker_provider,
    )
