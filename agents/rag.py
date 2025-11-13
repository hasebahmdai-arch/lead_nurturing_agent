from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import List

from langchain_core.documents import Document

from .embeddings import VectorStoreProvider


logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    documents: List[Document]

    def as_context(self, max_chars: int = 2000) -> str:
        content = "\n\n".join(doc.page_content for doc in self.documents)
        return content[:max_chars]


class ProjectRAGService:
    def __init__(self, *, vector_store_provider: VectorStoreProvider, default_collection: str = "projects"):
        self.vector_store_provider = vector_store_provider
        self.default_collection = default_collection

    def _collection_name(self, project_name: str | None) -> str:
        if project_name:
            normalized = project_name.lower().replace(" ", "_")
            return f"project_{normalized}"
        return self.default_collection

    def _fallback_documents(self, store, project_name: str | None, limit: int) -> List[Document]:
        logger.info("RAG fallback hit; fetching raw documents for project=%s", project_name or "<default>")
        where = {"project_name": project_name} if project_name else None
        raw = store.get(where=where, limit=limit if where else None)
        documents = raw.get("documents") or []
        metadatas = raw.get("metadatas") or []
        result: List[Document] = []
        for content, metadata in zip(documents, metadatas, strict=False):
            result.append(Document(page_content=content, metadata=metadata or {}))
            if len(result) >= limit:
                break
        return result

    def _similarity_search_with_variants(self, store, project_name: str | None, query: str, limit: int) -> List[Document]:
        search_prompts = [
            query,
            f"{project_name} project brochure highlights amenities features" if project_name else "",
            f"{project_name} brochure amenities location pricing" if project_name else "",
            "project highlights amenities floorplans pricing location",
        ]
        for prompt in search_prompts:
            if not prompt:
                continue
            docs = store.similarity_search(prompt, k=limit)
            if docs:
                logger.info(
                    "RAG retrieval succeeded project=%s query=%s chunks=%s",
                    project_name,
                    prompt,
                    len(docs),
                )
                return docs
        return []

    def get_documents(self, project_name: str | None, query: str, *, limit: int = 4) -> RetrievalResult:
        collection = self._collection_name(project_name)
        store = self.vector_store_provider.for_collection(collection)

        docs = self._similarity_search_with_variants(store, project_name, query, limit)

        if not docs and project_name:
            logger.info("RAG retrying with default collection for project=%s", project_name)
            default_store = self.vector_store_provider.for_collection(self.default_collection)
            docs = self._similarity_search_with_variants(default_store, None, query, limit)
            if not docs:
                docs = self._fallback_documents(default_store, project_name, limit)

        if not docs:
            docs = self._fallback_documents(store, project_name, limit)

        return RetrievalResult(documents=docs)

