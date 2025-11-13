from __future__ import annotations

import re
from dataclasses import dataclass
import logging
from datetime import datetime
from typing import Optional

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from agents.factory import get_agent, get_message_generator
from agents.personalization import PersonalizedMessage
from campaigns.schemas import AgentResponseSchema
from crm.models import Lead
from .models import (
    Campaign,
    CampaignLead,
    ConversationMessage,
    GoalOutcome,
    MessageStatus,
    SenderType,
)
from .schemas import AgentResponseRequest, CampaignCreateRequest


logger = logging.getLogger(__name__)


def _goal_from_intent(text: str) -> GoalOutcome:
    lowered = text.lower()
    visit_keywords = {"visit", "tour", "viewing", "see the property", "schedule a visit"}
    call_keywords = {"call", "phone", "discuss", "speak"}

    if any(keyword in lowered for keyword in visit_keywords):
        return GoalOutcome.VISIT
    if any(keyword in lowered for keyword in call_keywords):
        return GoalOutcome.CALL
    return GoalOutcome.NONE


@dataclass
class CampaignCreationResult:
    campaign: Campaign


class CampaignService:
    def __init__(self):
        self.message_generator = get_message_generator()

    @transaction.atomic
    def create_campaign(self, *, user, payload: CampaignCreateRequest) -> CampaignCreationResult:
        if not payload.lead_ids:
            raise ValidationError("Select at least one lead to create a campaign.")

        leads = list(Lead.objects.filter(id__in=payload.lead_ids))
        missing = set(payload.lead_ids) - {lead.id for lead in leads}
        if missing:
            raise ValidationError(f"Lead IDs not found: {', '.join(map(str, missing))}")

        campaign = Campaign.objects.create(
            name=payload.name,
            project_name=payload.project_name,
            message_channel=payload.message_channel,
            offer_details=payload.offer_details or "",
            filters=payload.filters_snapshot or {},
            created_by=user,
        )

        for lead in leads:
            message = self.message_generator.generate(campaign=campaign, lead=lead, offer_details=payload.offer_details)
            self._create_campaign_lead(campaign=campaign, lead=lead, message=message)

        return CampaignCreationResult(campaign=campaign)

    def _create_campaign_lead(self, *, campaign: Campaign, lead: Lead, message: PersonalizedMessage) -> CampaignLead:
        campaign_lead = CampaignLead.objects.create(
            campaign=campaign,
            lead=lead,
            personalized_message=message.body,
            status=MessageStatus.SENT,
            dispatch_time=timezone.now(),
        )
        ConversationMessage.objects.create(
            campaign_lead=campaign_lead,
            sender=SenderType.AGENT,
            message=message.body,
            metadata={
                "sources": message.sources,
                "context": message.context_snippet,
                "sent_to": settings.CAMPAIGN_EMAIL_OVERRIDE,
            },
        )
        self._dispatch_email(campaign=campaign, lead=lead, message=message.body)
        return campaign_lead

    def _dispatch_email(self, *, campaign: Campaign, lead: Lead, message: str) -> None:
        recipient = settings.CAMPAIGN_EMAIL_OVERRIDE
        if not recipient:
            raise ImproperlyConfigured(
                "CAMPAIGN_EMAIL_OVERRIDE must be set to route nurture emails to your test inbox."
            )

        subject = f"[{campaign.project_name}] Personalized follow-up for {lead.full_name}"
        logger.info(
            "Preparing email dispatch campaign_id=%s lead_id=%s recipient=%s backend=%s host=%s port=%s use_tls=%s use_ssl=%s from_email=%s",
            campaign.id,
            lead.id,
            recipient,
            settings.EMAIL_BACKEND,
            settings.EMAIL_HOST,
            settings.EMAIL_PORT,
            settings.EMAIL_USE_TLS,
            settings.EMAIL_USE_SSL,
            settings.DEFAULT_FROM_EMAIL,
        )
        logger.info(
            "Email credentials state host_user_set=%s host_password_set=%s",
            bool(settings.EMAIL_HOST_USER),
            bool(settings.EMAIL_HOST_PASSWORD),
        )
        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            logger.warning(
                "Email credentials missing; skipped dispatch campaign_id=%s lead_id=%s",
                campaign.id,
                lead.id,
            )
            return

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
            logger.info(
                "Campaign email dispatched campaign_id=%s lead_id=%s recipient=%s",
                campaign.id,
                lead.id,
                recipient,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to dispatch campaign email campaign_id=%s lead_id=%s error=%s",
                campaign.id,
                lead.id,
                exc,
                exc_info=True,
            )
            if settings.DEBUG:
                logger.warning(
                    "DEBUG=True; continuing despite email failure campaign_id=%s lead_id=%s",
                    campaign.id,
                    lead.id,
                )
            else:
                raise


class CampaignDashboardService:
    def get_dashboard(self, *, campaign: Campaign):
        leads = list(
            campaign.lead_links.select_related("lead").prefetch_related("messages")
        )
        metrics = {
            "total_leads": campaign.total_leads(),
            "messages_sent": campaign.messages_sent(),
            "leads_responded": campaign.responses_received(),
            "goals_completed": campaign.goals_completed(),
        }
        return leads, metrics


class ConversationService:
    def __init__(self):
        self.agent = get_agent()

    def _build_thread_id(self, campaign_lead: CampaignLead) -> str:
        return f"campaign-lead-{campaign_lead.id}"

    @transaction.atomic
    def handle_customer_message(self, *, campaign_lead: CampaignLead, payload: AgentResponseRequest) -> AgentResponseSchema:
        goal = payload.requested_goal or _goal_from_intent(payload.customer_message)
        goal_value = getattr(goal, "value", goal)

        ConversationMessage.objects.create(
            campaign_lead=campaign_lead,
            sender=SenderType.CUSTOMER,
            message=payload.customer_message,
            intent=goal_value or GoalOutcome.NONE,
        )
        campaign_lead.mark_responded()

        if goal != GoalOutcome.NONE:
            campaign_lead.mark_goal(goal, scheduled_for=payload.proposed_schedule)
            reply = self._goal_confirmation_message(campaign_lead=campaign_lead, goal=goal, schedule=payload.proposed_schedule)
            ConversationMessage.objects.create(
                campaign_lead=campaign_lead,
                sender=SenderType.AGENT,
                message=reply,
                intent=goal_value,
                metadata={"route": "goal_confirmation"},
            )
            return AgentResponseSchema(
                reply=reply,
                intent=goal,
                goal_outcome=goal,
                scheduled_time=payload.proposed_schedule,
            )

        agent_result = self.agent.run(
            query=payload.customer_message,
            campaign_lead=campaign_lead,
            thread_id=self._build_thread_id(campaign_lead),
        )
        reply_text = agent_result.get("message") or agent_result.get("answer") or "Thank you for reaching out. I'll get back to you shortly."
        route = agent_result.get("route", "rag")
        ConversationMessage.objects.create(
            campaign_lead=campaign_lead,
            sender=SenderType.AGENT,
            message=reply_text,
            intent=GoalOutcome.NONE,
            metadata={"route": route, "sources": agent_result.get("sources"), "sql": agent_result.get("sql")},
        )
        campaign_lead.last_agent_message_at = timezone.now()
        campaign_lead.save(update_fields=["last_agent_message_at", "updated_at"])

        return AgentResponseSchema(
            reply=reply_text,
            intent=GoalOutcome.NONE,
            goal_outcome=GoalOutcome.NONE,
        )

    def _goal_confirmation_message(
        self,
        *,
        campaign_lead: CampaignLead,
        goal: GoalOutcome,
        schedule: Optional[datetime],
    ) -> str:
        lead = campaign_lead.lead
        campaign = campaign_lead.campaign
        schedule_text = schedule.strftime("%A, %d %B at %H:%M") if schedule else "the earliest available slot"
        if goal == GoalOutcome.VISIT:
            return (
                f"Wonderful news, {lead.first_name}! I've reserved a property viewing for {schedule_text} at {campaign.project_name}. "
                f"Our sales team will confirm the details over email shortly."
            )
        return (
            f"Great, {lead.first_name}! I've scheduled a call for {schedule_text} to walk you through {campaign.project_name}. "
            f"A sales advisor will reach out from the official line."
        )

