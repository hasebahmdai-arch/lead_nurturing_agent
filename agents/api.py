from __future__ import annotations

from typing import List

from django.shortcuts import get_object_or_404
from ninja import File, Router
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja_jwt.authentication import JWTAuth

from campaigns.models import CampaignLead
from .factory import get_agent, get_ingestion_service
from .schemas import AgentQueryRequest, AgentQueryResponse, DocumentUploadResponse

router = Router(tags=["agent"])
auth = JWTAuth()


@router.post("/documents/upload", response=List[DocumentUploadResponse], auth=auth)
def upload_documents(request, files: List[UploadedFile] = File(...), project_name: str | None = None):
    ingestion_service = get_ingestion_service()
    responses: List[DocumentUploadResponse] = []
    for uploaded_file in files:
        try:
            brochure = ingestion_service.store_upload(
                uploaded_file=uploaded_file,
                project_name=project_name,
                content_type=uploaded_file.content_type,
                user=request.user,
            )
            outcome = ingestion_service.ingest(brochure)
        except Exception as exc:  # noqa: BLE001
            raise HttpError(400, f"Failed to ingest {uploaded_file.name}: {exc}") from exc

        responses.append(
            DocumentUploadResponse(
                document_id=brochure.id,
                project_name=brochure.project_name,
                chunks_indexed=outcome.chunks_indexed,
                collection_name=outcome.collection_name,
            )
        )
    return responses


@router.post("/query", response=AgentQueryResponse, auth=auth)
def agent_query(request, payload: AgentQueryRequest):
    campaign_lead = get_object_or_404(
        CampaignLead,
        pk=payload.campaign_lead_id,
        campaign__created_by=request.user,
    )

    agent = get_agent()
    result = agent.run(
        query=payload.query,
        campaign_lead=campaign_lead,
        thread_id=f"campaign-lead-{campaign_lead.id}",
    )
    reply = result.get("message") or result.get("answer")
    if not reply:
        raise HttpError(500, "Unable to generate agent response.")

    return AgentQueryResponse(
        route=result.get("route", "rag"),
        reply=reply,
        sql=result.get("sql"),
        rows=result.get("rows"),
        sources=result.get("sources"),
    )

