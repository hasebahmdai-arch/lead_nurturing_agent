from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from crm.models import Lead, ProjectName


class MessageChannel(models.TextChoices):
    EMAIL = "email", "Email"
    WHATSAPP = "whatsapp", "WhatsApp"


class MessageStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    RESPONDED = "responded", "Responded"
    GOAL_MET = "goal_met", "Goal Met"


class GoalOutcome(models.TextChoices):
    NONE = "none", "None"
    CALL = "call", "Sales Call Scheduled"
    VISIT = "visit", "Property Visit Scheduled"


class SenderType(models.TextChoices):
    AGENT = "agent", "AI Agent"
    CUSTOMER = "customer", "Customer"
    SALES = "sales", "Sales Associate"


class Campaign(models.Model):
    name = models.CharField(max_length=128)
    project_name = models.CharField(max_length=64, choices=ProjectName.choices)
    message_channel = models.CharField(max_length=32, choices=MessageChannel.choices, default=MessageChannel.EMAIL)
    offer_details = models.TextField(blank=True)
    filters = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="campaigns",
        on_delete=models.PROTECT,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.name} ({self.project_name})"

    def total_leads(self) -> int:
        return self.lead_links.count()

    def messages_sent(self) -> int:
        return self.lead_links.exclude(personalized_message="").count()

    def responses_received(self) -> int:
        return self.lead_links.filter(status__in=[MessageStatus.RESPONDED, MessageStatus.GOAL_MET]).count()

    def goals_completed(self) -> int:
        return self.lead_links.filter(goal_outcome__in=[GoalOutcome.CALL, GoalOutcome.VISIT]).count()


class CampaignLead(models.Model):
    campaign = models.ForeignKey(Campaign, related_name="lead_links", on_delete=models.CASCADE)
    lead = models.ForeignKey(Lead, related_name="campaign_links", on_delete=models.CASCADE)
    shortlisted_at = models.DateTimeField(auto_now_add=True)
    personalized_message = models.TextField(blank=True)
    dispatch_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=MessageStatus.choices, default=MessageStatus.PENDING)
    goal_outcome = models.CharField(max_length=32, choices=GoalOutcome.choices, default=GoalOutcome.NONE)
    scheduled_datetime = models.DateTimeField(null=True, blank=True)
    last_customer_message_at = models.DateTimeField(null=True, blank=True)
    last_agent_message_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("campaign", "lead")
        ordering = ("-shortlisted_at",)

    def mark_sent(self):
        self.status = MessageStatus.SENT
        self.dispatch_time = timezone.now()
        self.save(update_fields=["status", "dispatch_time", "updated_at"])

    def mark_responded(self):
        if self.status != MessageStatus.GOAL_MET:
            self.status = MessageStatus.RESPONDED
        self.last_customer_message_at = timezone.now()
        self.save(update_fields=["status", "last_customer_message_at", "updated_at"])

    def mark_goal(self, outcome: str, scheduled_for=None):
        self.goal_outcome = outcome
        self.status = MessageStatus.GOAL_MET
        self.scheduled_datetime = scheduled_for
        self.last_agent_message_at = timezone.now()
        self.save(update_fields=["goal_outcome", "status", "scheduled_datetime", "last_agent_message_at", "updated_at"])


class ConversationMessage(models.Model):
    campaign_lead = models.ForeignKey(CampaignLead, related_name="messages", on_delete=models.CASCADE)
    sender = models.CharField(max_length=16, choices=SenderType.choices)
    message = models.TextField()
    intent = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"{self.sender} -> {self.campaign_lead.lead.full_name}"
