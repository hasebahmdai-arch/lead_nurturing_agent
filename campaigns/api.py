from __future__ import annotations

from typing import List

from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from .models import Campaign, CampaignLead
from crm.schemas import LeadSchema
from .schemas import (
    AgentResponseRequest,
    AgentResponseSchema,
    CampaignCreateRequest,
    CampaignDashboardResponse,
    CampaignDetailSchema,
    CampaignMetricsSchema,
    CampaignSchema,
    CampaignLeadSchema,
    ConversationThreadResponse,
    ConversationMessageSchema,
)
from .services import CampaignDashboardService, CampaignService, ConversationService

router = Router(tags=["campaigns"])
auth = JWTAuth()


@router.get("/", response=List[CampaignSchema], auth=auth)
def list_campaigns(request):
    queryset = Campaign.objects.filter(created_by=request.user).order_by("-created_at")
    return [CampaignSchema.from_orm(campaign) for campaign in queryset]


@router.post("/", response=CampaignDetailSchema, auth=auth)
def create_campaign(request, payload: CampaignCreateRequest):
    service = CampaignService()
    try:
        result = service.create_campaign(user=request.user, payload=payload)
    except Exception as exc:  # noqa: BLE001
        raise HttpError(400, str(exc))

    campaign = result.campaign
    leads = list(campaign.lead_links.select_related("lead"))
    return CampaignDetailSchema(
        **CampaignSchema.from_orm(campaign).dict(),
        leads=[CampaignLeadSchema.from_orm(link) for link in leads],
    )


@router.get("/{campaign_id}/dashboard", response=CampaignDashboardResponse, auth=auth)
def campaign_dashboard(request, campaign_id: int):
    campaign = get_object_or_404(Campaign, pk=campaign_id, created_by=request.user)
    dashboard_service = CampaignDashboardService()
    leads, metrics = dashboard_service.get_dashboard(campaign=campaign)

    return CampaignDashboardResponse(
        campaign=CampaignSchema.from_orm(campaign),
        metrics=CampaignMetricsSchema(**metrics),
        leads=[CampaignLeadSchema.from_orm(link) for link in leads],
    )


@router.get("/{campaign_id}/followups/{campaign_lead_id}", response=ConversationThreadResponse, auth=auth)
def fetch_conversation(request, campaign_id: int, campaign_lead_id: int):
    campaign = get_object_or_404(Campaign, pk=campaign_id, created_by=request.user)
    campaign_lead = get_object_or_404(CampaignLead, pk=campaign_lead_id, campaign=campaign)
    messages = [
        ConversationMessageSchema.from_orm(message)
        for message in campaign_lead.messages.order_by("created_at")
    ]
    return ConversationThreadResponse(
        lead=LeadSchema.from_orm(campaign_lead.lead),
        messages=messages,
    )


@router.post("/followups/{campaign_lead_id}/respond", response=AgentResponseSchema, auth=auth)
def agent_respond(request, campaign_lead_id: int, payload: AgentResponseRequest):
    campaign_lead = get_object_or_404(
        CampaignLead,
        pk=campaign_lead_id,
        campaign__created_by=request.user,
    )
    service = ConversationService()
    response = service.handle_customer_message(campaign_lead=campaign_lead, payload=payload)
    return response

