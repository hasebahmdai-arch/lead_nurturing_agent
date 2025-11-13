from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from crm.models import Lead

from agents.personalization import PersonalizedMessage


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("VANNA_MODEL", "test-model")


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(username="agent_user", password="secret123", email="agent@example.com")


@pytest.fixture
def auth_client(client, user):
    response = client.post(
        "/api/auth/token",
        {"username": user.username, "password": "secret123"},
        content_type="application/json",
    )
    tokens = response.json()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {tokens['access']}"
    return client


class StubMessageGenerator:
    def generate(self, *, campaign, lead, offer_details):
        offer_note = f" Offer: {offer_details}." if offer_details else ""
        body = (
            f"Hi {lead.first_name}, revisiting {campaign.project_name} tailored to your {lead.unit_type} preference."
            f"{offer_note} Let's schedule a visit!"
        )
        return PersonalizedMessage(body=body, sources=["stub"], context_snippet="amenities, location, pricing")


@pytest.fixture
def stub_message_generator(monkeypatch):
    generator = StubMessageGenerator()
    monkeypatch.setattr("campaigns.services.get_message_generator", lambda: generator)
    return generator


@pytest.fixture
def lead_factory(db):
    def factory(**kwargs):
        defaults = {
            "crm_id": f"CRM-{kwargs.get('first_name', 'Lead')}-{kwargs.get('last_name', 'Test')}",
            "first_name": "Jamie",
            "last_name": "Doe",
            "email": f"jamie{Lead.objects.count()}@example.com",
            "phone_number": "+1234567890",
            "project_enquired": "Altura",
            "unit_type": "2 bed",
            "status": "connected",
            "budget_min": 500000,
            "budget_max": 800000,
        }
        defaults.update(kwargs)
        return Lead.objects.create(**defaults)

    return factory

