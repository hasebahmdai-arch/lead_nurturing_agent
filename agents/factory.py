from __future__ import annotations

from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from langchain_google_genai import ChatGoogleGenerativeAI

from .embeddings import EmbeddingFactory, VectorStoreProvider
from .ingestion import DocumentIngestionService
from .langgraph_agent import LeadNurtureAgent
from .personalization import PersonalizedMessageGenerator
from .rag import ProjectRAGService
from .t2sql import VannaTextToSQLService


@lru_cache(maxsize=1)
def get_embedding_factory() -> EmbeddingFactory:
    return EmbeddingFactory()


@lru_cache(maxsize=1)
def get_vector_store_provider() -> VectorStoreProvider:
    return VectorStoreProvider(embedding_factory=get_embedding_factory())


@lru_cache(maxsize=1)
def get_rag_service() -> ProjectRAGService:
    return ProjectRAGService(vector_store_provider=get_vector_store_provider())


@lru_cache(maxsize=1)
def get_message_generator() -> PersonalizedMessageGenerator:
    return PersonalizedMessageGenerator(rag_service=get_rag_service())


@lru_cache(maxsize=1)
def get_ingestion_service() -> DocumentIngestionService:
    return DocumentIngestionService(vector_store_provider=get_vector_store_provider())


@lru_cache(maxsize=1)
def get_t2sql_service() -> VannaTextToSQLService:
    return VannaTextToSQLService()


@lru_cache(maxsize=1)
def get_agent() -> LeadNurtureAgent:
    from os import getenv

    api_key = getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ImproperlyConfigured("GOOGLE_API_KEY must be configured for Gemini access.")
    llm = ChatGoogleGenerativeAI(
        model=settings.AGENT_ROUTER_MODEL,
        temperature=0.2,
        google_api_key=api_key,
    )
    return LeadNurtureAgent(
        rag_service=get_rag_service(),
        t2sql_service=get_t2sql_service(),
        formatter=None,
        llm=llm,
    )

