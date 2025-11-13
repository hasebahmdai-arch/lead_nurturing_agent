from __future__ import annotations

from typing import List, Optional

from ninja import Schema

from campaigns.schemas import AgentResponseSchema


class DocumentUploadResponse(Schema):
    document_id: int
    project_name: str
    chunks_indexed: int
    collection_name: str


class AgentQueryRequest(Schema):
    campaign_lead_id: int
    query: str


class AgentQueryResponse(Schema):
    route: str
    reply: str
    sql: Optional[str] = None
    rows: Optional[list] = None
    sources: Optional[List[str]] = None

