from __future__ import annotations

import pytest

from crm.models import LeadStatus, ProjectName


@pytest.mark.django_db
def test_shortlist_requires_two_filters(auth_client):
    response = auth_client.post(
        "/api/leads/shortlist",
        {"project_names": [ProjectName.ALTURA]},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "Please select at least" in response.json()["detail"]


@pytest.mark.django_db
def test_shortlist_returns_filtered_leads(auth_client, lead_factory):
    lead_factory(first_name="Jamie", email="jamie@example.com", status=LeadStatus.CONNECTED)
    lead_factory(first_name="Taylor", email="taylor@example.com", status=LeadStatus.NOT_INTERESTED)
    lead_factory(first_name="Chris", email="chris@example.com", project_enquired=ProjectName.DLF_WEST_PARK)

    payload = {
        "project_names": [ProjectName.ALTURA],
        "lead_status": LeadStatus.CONNECTED,
    }
    response = auth_client.post("/api/leads/shortlist", payload, content_type="application/json")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["leads"][0]["first_name"] == "Jamie"

