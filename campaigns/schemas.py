from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from ninja import ModelSchema, Schema

from crm.models import Lead
from crm.schemas import LeadSchema
from .models import (
    Campaign,
    CampaignLead,
    ConversationMessage,
    GoalOutcome,
    MessageChannel,
    MessageStatus,
)


class CampaignLeadSchema(Schema):
    id: int
    lead: LeadSchema
    status: str
    goal_outcome: str
    personalized_message: str
    dispatch_time: Optional[datetime]
    scheduled_datetime: Optional[datetime]
    last_customer_message_at: Optional[datetime]
    last_agent_message_at: Optional[datetime]
    shortlisted_at: datetime

    @classmethod
    def from_orm(cls, obj: CampaignLead) -> "CampaignLeadSchema":
        return cls(
            id=obj.id,
            lead=LeadSchema.from_orm(obj.lead),
            status=obj.status,
            goal_outcome=obj.goal_outcome,
            personalized_message=obj.personalized_message,
            dispatch_time=obj.dispatch_time,
            scheduled_datetime=obj.scheduled_datetime,
            last_customer_message_at=obj.last_customer_message_at,
            last_agent_message_at=obj.last_agent_message_at,
            shortlisted_at=obj.shortlisted_at,
        )


class CampaignSchema(ModelSchema):
    class Config:
        model = Campaign
        model_fields = [
            "id",
            "name",
            "project_name",
            "message_channel",
            "offer_details",
            "filters",
            "created_at",
            "updated_at",
        ]


class CampaignDetailSchema(CampaignSchema):
    leads: List[CampaignLeadSchema]


class CampaignCreateRequest(Schema):
    name: str
    project_name: str
    message_channel: MessageChannel
    offer_details: Optional[str] = None
    lead_ids: List[int]
    filters_snapshot: Optional[dict] = None


class CampaignMetricsSchema(Schema):
    total_leads: int
    messages_sent: int
    leads_responded: int
    goals_completed: int


class CampaignDashboardResponse(Schema):
    campaign: CampaignSchema
    metrics: CampaignMetricsSchema
    leads: List[CampaignLeadSchema]


class ConversationMessageSchema(ModelSchema):
    class Config:
        model = ConversationMessage
        model_fields = [
            "id",
            "sender",
            "message",
            "intent",
            "metadata",
            "created_at",
        ]


class ConversationThreadResponse(Schema):
    lead: LeadSchema
    messages: List[ConversationMessageSchema]


class AgentResponseRequest(Schema):
    campaign_lead_id: int
    customer_message: str
    requested_goal: Optional[GoalOutcome] = None
    proposed_schedule: Optional[datetime] = None


class AgentResponseSchema(Schema):
    reply: str
    intent: str
    goal_outcome: GoalOutcome
    scheduled_time: Optional[datetime] = None

