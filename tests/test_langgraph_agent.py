from __future__ import annotations

import pytest
from langchain_core.documents import Document

from agents.langgraph_agent import LeadNurtureAgent, T2SQLAnswerFormatter
from agents.rag import RetrievalResult
from agents.t2sql import TextToSQLResult
from campaigns.models import Campaign, CampaignLead
from crm.models import Lead


class DummyLLM:
    def __init__(self, prefix: str):
        self.prefix = prefix

    def invoke(self, prompt: str):
        class Response:
            def __init__(self, content):
                self.content = content

        lower = prompt.lower()
        if "answer (t2sql or rag)" in lower or "respond with only" in lower:
            question_text = lower.split("question:", 1)[-1] if "question:" in lower else lower
            if any(
                keyword in question_text
                for keyword in ("count", "number", "average", "total", "sum", "metric", "how many")
            ):
                return Response("T2SQL")
            return Response("RAG")
        return Response(f"{self.prefix} {prompt.splitlines()[0]}")


class StubRAGService:
    def get_documents(self, project_name: str | None, query: str, limit: int = 4):
        return RetrievalResult(documents=[Document(page_content="Infinity pool and skyline views.")])


class StubT2SQLService:
    def __init__(self):
        self.queries = []

    def answer(self, question: str) -> TextToSQLResult:
        self.queries.append(question)
        return TextToSQLResult(
            sql="SELECT COUNT(*) as lead_count FROM crm_lead",
            rows=[{"lead_count": 7}],
            explanation="Counts the number of leads.",
        )


@pytest.fixture
def lead(db):
    return Lead.objects.create(
        crm_id="CRM-001",
        first_name="Jordan",
        last_name="Miles",
        email="jordan@example.com",
        phone_number="+1234567890",
        project_enquired="Altura",
        unit_type="2 bed",
        status="connected",
    )


@pytest.fixture
def campaign(db, user, lead):
    campaign = Campaign.objects.create(
        name="Test Campaign",
        project_name="Altura",
        message_channel="email",
        created_by=user,
    )
    CampaignLead.objects.create(campaign=campaign, lead=lead)
    return campaign


@pytest.mark.django_db
def test_agent_routes_to_sql(lead, campaign):
    campaign_lead = campaign.lead_links.first()
    t2sql_stub = StubT2SQLService()
    agent = LeadNurtureAgent(
        rag_service=StubRAGService(),
        t2sql_service=t2sql_stub,
        formatter=T2SQLAnswerFormatter(),
        llm=DummyLLM("Answer:"),
    )
    result = agent.run(
        query="How many leads have status connected?",
        campaign_lead=campaign_lead,
        thread_id="test-thread",
    )
    assert result["route"] == "t2sql"
    assert "7" in result["message"]
    assert t2sql_stub.queries == ["How many leads have status connected?"]


@pytest.mark.django_db
def test_agent_routes_to_rag(lead, campaign):
    campaign_lead = campaign.lead_links.first()
    agent = LeadNurtureAgent(
        rag_service=StubRAGService(),
        t2sql_service=StubT2SQLService(),
        formatter=T2SQLAnswerFormatter(),
        llm=DummyLLM("CTA:"),
    )
    result = agent.run(
        query="What amenities can I highlight?",
        campaign_lead=campaign_lead,
        thread_id="test-thread-2",
    )
    assert result["route"] == "rag"
    assert "CTA:" in result["answer"]

