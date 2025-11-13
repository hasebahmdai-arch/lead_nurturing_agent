from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import List

from django.db import transaction
from django.utils import timezone
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from crm.models import ProjectName
from .embeddings import VectorStoreProvider
from .models import BrochureDocument, DocumentIngestionLog


@dataclass
class IngestionOutcome:
    chunks_indexed: int
    collection_name: str


class DocumentIngestionService:
    def __init__(
        self,
        *,
        vector_store_provider: VectorStoreProvider,
        splitter: RecursiveCharacterTextSplitter | None = None,
    ) -> None:
        self.vector_store_provider = vector_store_provider
        self.splitter = splitter or RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)

    def _collection_name(self, project_name: str | None) -> str:
        if project_name:
            normalized = project_name.lower().replace(" ", "_")
            return f"project_{normalized}"
        return "projects"

    def _load_documents(self, file_path: str, content_type: str | None) -> List[Document]:
        if content_type == "application/pdf" or file_path.lower().endswith(".pdf"):
            loader = PyPDFLoader(file_path)
            return loader.load()

        loader = TextLoader(file_path, autodetect_encoding=True)
        return loader.load()

    def ingest(self, brochure: BrochureDocument) -> IngestionOutcome:
        content_type, _ = mimetypes.guess_type(brochure.file.name)
        try:
            documents = self._load_documents(brochure.file.path, brochure.content_type or content_type)
            chunks = self.splitter.split_documents(documents)

            collection_name = self._collection_name(brochure.project_name)
            store = self.vector_store_provider.for_collection(collection_name)

            for idx, chunk in enumerate(chunks):
                chunk.metadata = {
                    **chunk.metadata,
                    "document_id": str(brochure.id),
                    "project_name": brochure.project_name,
                    "source": brochure.file.name,
                    "chunk_index": idx,
                }

            store.delete(where={"document_id": str(brochure.id)})
            store.add_documents(documents=chunks)
            store.persist()

            brochure.mark_indexed()
            DocumentIngestionLog.objects.create(
                document=brochure,
                status="completed",
                detail=f"Ingested {len(chunks)} chunks into {collection_name}",
                chunks_indexed=len(chunks),
            )

            return IngestionOutcome(chunks_indexed=len(chunks), collection_name=collection_name)
        except Exception as exc:  # noqa: BLE001
            DocumentIngestionLog.objects.create(
                document=brochure,
                status="failed",
                detail=str(exc),
                chunks_indexed=0,
            )
            raise

    def _detect_project_name(self, filename: str) -> str:
        normalized = filename.lower().replace("-", " ").replace("_", " ")
        for choice, label in ProjectName.choices:
            candidate = label.lower()
            if candidate in normalized:
                return choice
        return ""

    @transaction.atomic
    def store_upload(self, *, uploaded_file, project_name: str | None, content_type: str | None, user) -> BrochureDocument:
        original_name = Path(uploaded_file.name).name
        detected_project = project_name or self._detect_project_name(original_name)
        brochure = BrochureDocument.objects.create(
            project_name=detected_project or "",
            original_name=original_name,
            content_type=content_type or getattr(uploaded_file, "content_type", "") or "",
            uploaded_by=user if getattr(user, "is_authenticated", False) else None,
            metadata={},
        )

        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)
        brochure.file.save(original_name, uploaded_file, save=True)
        brochure.refresh_from_db()
        return brochure

