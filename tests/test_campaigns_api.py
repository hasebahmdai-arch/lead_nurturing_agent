from __future__ import annotations

import pytest
from django.utils import timezone

from campaigns.models import CampaignLead, ConversationMessage, GoalOutcome


@pytest.mark.django_db
def test_campaign_creation_generates_messages(auth_client, lead_factory, stub_message_generator):
    lead = lead_factory(email="lead1@example.com")

    payload = {
        "name": "Nurturing Campaign 1",
        "project_name": lead.project_enquired,
        "message_channel": "email",
        "offer_details": "Zero processing fee this month",
        "lead_ids": [lead.id],
        "filters_snapshot": {"project_names": [lead.project_enquired], "lead_status": lead.status},
    }
    response = auth_client.post("/api/campaigns/", payload, content_type="application/json")
    assert response.status_code == 200

    data = response.json()
    assert data["name"] == "Nurturing Campaign 1"
    assert len(data["leads"]) == 1
    campaign_lead = CampaignLead.objects.get(id=data["leads"][0]["id"])
    assert campaign_lead.status == "sent"
    assert "Zero processing fee" in campaign_lead.personalized_message

    conversation = ConversationMessage.objects.filter(campaign_lead=campaign_lead, sender="agent").first()
    assert conversation is not None
    assert "Zero processing fee" in conversation.message


class StubAgent:
    def __init__(self):
        self.calls = []

    def run(self, *, query, campaign_lead, thread_id):
        self.calls.append({"query": query, "thread_id": thread_id})
        return {"route": "rag", "answer": "Here are the amenities you asked for.", "sources": ["stub.pdf"]}


@pytest.mark.django_db
def test_agent_followup_response(auth_client, lead_factory, stub_message_generator, monkeypatch):
    lead = lead_factory(email="lead2@example.com")
    payload = {
        "name": "Campaign Followup",
        "project_name": lead.project_enquired,
        "message_channel": "email",
        "offer_details": "",
        "lead_ids": [lead.id],
        "filters_snapshot": {"project_names": [lead.project_enquired], "lead_status": lead.status},
    }
    campaign_response = auth_client.post("/api/campaigns/", payload, content_type="application/json")
    campaign_lead_id = campaign_response.json()["leads"][0]["id"]

    agent_stub = StubAgent()
    monkeypatch.setattr("campaigns.services.get_agent", lambda: agent_stub)

    followup_payload = {
        "campaign_lead_id": campaign_lead_id,
        "customer_message": "Could you remind me about the amenities?",
    }
    response = auth_client.post(
        f"/api/campaigns/followups/{campaign_lead_id}/respond",
        followup_payload,
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["reply"].startswith("Here are the amenities")
    conversation_entries = ConversationMessage.objects.filter(campaign_lead_id=campaign_lead_id).order_by("created_at")
    assert conversation_entries.count() == 3  # initial agent message, customer reply, agent follow-up
    assert conversation_entries.last().metadata["route"] == "rag"


@pytest.mark.django_db
def test_goal_detection_triggers_confirmation(auth_client, lead_factory, stub_message_generator, monkeypatch):
    lead = lead_factory(email="lead3@example.com")
    payload = {
        "name": "Goal Campaign",
        "project_name": lead.project_enquired,
        "message_channel": "email",
        "offer_details": "",
        "lead_ids": [lead.id],
        "filters_snapshot": {"project_names": [lead.project_enquired], "lead_status": lead.status},
    }
    campaign_response = auth_client.post("/api/campaigns/", payload, content_type="application/json")
    campaign_lead_id = campaign_response.json()["leads"][0]["id"]

    monkeypatch.setattr("campaigns.services.get_agent", lambda: StubAgent())
    schedule_time = timezone.now()
    followup_payload = {
        "campaign_lead_id": campaign_lead_id,
        "customer_message": "Let's schedule a property visit this weekend.",
        "proposed_schedule": schedule_time.isoformat(),
    }
    response = auth_client.post(
        f"/api/campaigns/followups/{campaign_lead_id}/respond",
        followup_payload,
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["goal_outcome"] == GoalOutcome.VISIT
    hub = CampaignLead.objects.get(id=campaign_lead_id)
    assert hub.goal_outcome == GoalOutcome.VISIT
    assert "reserved a property viewing" in ConversationMessage.objects.filter(
        campaign_lead_id=campaign_lead_id, sender="agent"
    ).last().message

