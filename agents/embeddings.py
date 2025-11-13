from __future__ import annotations

import os
from typing import Optional

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.embeddings import Embeddings


class EmbeddingFactory:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model_name: str = "models/text-embedding-004",
    ) -> None:
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ImproperlyConfigured("GOOGLE_API_KEY is required for Google Gemini embeddings.")
        self.model_name = model_name

    def build(self) -> Embeddings:
        return GoogleGenerativeAIEmbeddings(
            model=self.model_name,
            google_api_key=self.api_key,
        )


class VectorStoreProvider:
    def __init__(self, *, embedding_factory: EmbeddingFactory, persist_directory: Optional[str] = None) -> None:
        self.embedding_factory = embedding_factory
        self.persist_directory = persist_directory or settings.CHROMA_DB_DIR

    def for_collection(self, collection_name: str) -> Chroma:
        embeddings = self.embedding_factory.build()
        return Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=self.persist_directory,
        )

