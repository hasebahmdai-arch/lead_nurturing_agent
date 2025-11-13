from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from deepeval import evaluate  # noqa: E402
from deepeval.evaluate.configs import DisplayConfig  # noqa: E402
from deepeval.metrics import BaseMetric  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402
from langchain_core.documents import Document  # noqa: E402

from agents.langgraph_agent import LeadNurtureAgent, T2SQLAnswerFormatter  # noqa: E402
from agents.rag import RetrievalResult  # noqa: E402
from agents.t2sql import TextToSQLResult  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402

from campaigns.models import Campaign, CampaignLead  # noqa: E402
from crm.models import Lead  # noqa: E402


class KeywordCoverageMetric(BaseMetric):
    metric_name = "KeywordCoverage"
    async_mode = False

    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold
        self.success = False
        self.score = 0.0

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        keywords: List[str] = test_case.additional_metadata.get("keywords", [])
        output = (test_case.actual_output or "").lower()
        missing = [kw for kw in keywords if kw.lower() not in output]
        if not keywords:
            self.score = 1.0
            self.success = True
            self.reason = "No keywords defined for evaluation."
            return self.score
        self.score = max(0.0, 1 - len(missing) / len(keywords))
        self.success = self.score >= self.threshold
        self.reason = (
            "All expected keywords present." if not missing else f"Missing keywords: {', '.join(missing)}"
        )
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return bool(getattr(self, "success", False))


class RouteAccuracyMetric(BaseMetric):
    metric_name = "RouteAccuracy"
    async_mode = False

    def __init__(self):
        self.threshold = 1.0
        self.success = False
        self.score = 0.0

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        expected = test_case.additional_metadata.get("expected_route")
        actual = test_case.additional_metadata.get("route")
        self.success = expected == actual
        self.score = 1.0 if self.success else 0.0
        self.success = self.score >= self.threshold
        self.reason = (
            f"Route matched expected '{expected}'."
            if self.success
            else f"Expected route '{expected}' but got '{actual}'."
        )
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return bool(getattr(self, "success", False))


class EvalRAGService:
    def get_documents(self, project_name: str | None, query: str, limit: int = 4) -> RetrievalResult:
        return RetrievalResult(
            documents=[
                Document(page_content="Panoramic skyline views and an infinity pool perfect for families."),
                Document(page_content="Co-working lounge and quick access to the metro station."),
            ]
        )


class EvalT2SQLService:
    def answer(self, question: str) -> TextToSQLResult:
        return TextToSQLResult(
            sql="SELECT COUNT(*) as lead_count FROM crm_lead WHERE status = 'connected';",
            rows=[{"lead_count": 7}],
            explanation="Counts the number of connected leads in the CRM.",
        )


class StubLLM:
    """Simple LLM stub that echoes brochure highlights for deterministic tests."""

    def invoke(self, prompt: str):
        class Response:
            def __init__(self, content: str):
                self.content = content

        prompt_lower = prompt.lower()
        if "answer (t2sql or rag)" in prompt_lower or "respond with only" in prompt_lower:
            question_text = (
                prompt_lower.split("question:", 1)[-1]
                if "question:" in prompt_lower
                else prompt_lower
            )
            if any(
                keyword in question_text
                for keyword in ("count", "number", "average", "total", "budget", "sum", "metric", "how many")
            ):
                return Response("T2SQL")
            return Response("RAG")
        if "panoramic skyline views" in prompt_lower:
            content = (
                "Highlight the panoramic skyline views, the infinity pool for families, "
                "and the co-working lounge close to the metro for Morgan."
            )
        else:
            content = "Here is the requested information."
        return Response(content)


def prepare_seed_data() -> CampaignLead:
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="evaluation_user",
        defaults={"email": "evaluation@example.com"},
    )
    if not user.password:
        user.set_password("eval-password")
        user.save(update_fields=["password"])

    lead, _ = Lead.objects.get_or_create(
        crm_id="EVAL-LEAD-1",
        defaults=dict(
            first_name="Morgan",
            last_name="Shaw",
            email="morgan@example.com",
            phone_number="+1234567890",
            project_enquired="Altura",
            unit_type="2 bed",
            status="connected",
            budget_min=550000,
            budget_max=780000,
            last_conversation_summary="Asked about amenities suitable for young children.",
        ),
    )
    campaign, _ = Campaign.objects.get_or_create(
        name="Evaluation Campaign",
        defaults=dict(
            project_name="Altura",
            message_channel="email",
            created_by=user,
        ),
    )
    if campaign.created_by_id is None:
        campaign.created_by = user
        campaign.save(update_fields=["created_by"])
    campaign_lead, _ = CampaignLead.objects.get_or_create(campaign=campaign, lead=lead)
    return campaign_lead


def main():
    campaign_lead = prepare_seed_data()
    agent = LeadNurtureAgent(
        rag_service=EvalRAGService(),
        t2sql_service=EvalT2SQLService(),
        formatter=T2SQLAnswerFormatter(),
        llm=StubLLM(),
    )

    scenarios = [
        {
            "query": "How many leads are currently marked as connected?",
            "expected_route": "t2sql",
            "keywords": ["lead", "connected", "7"],
        },
        {
            "query": "Which amenities should I highlight for Morgan's family?",
            "expected_route": "rag",
            "keywords": ["skyline", "infinity pool", "co-working"],
        },
    ]

    test_cases: List[LLMTestCase] = []

    for scenario in scenarios:
        result = agent.run(query=scenario["query"], campaign_lead=campaign_lead, thread_id="eval-thread")
        output = result.get("message") or result.get("answer", "")
        metadata = {
            "expected_route": scenario["expected_route"],
            "route": result.get("route"),
            "keywords": scenario["keywords"],
            "raw_result": result,
        }
        test_cases.append(
            LLMTestCase(
                input=scenario["query"],
                actual_output=output,
                expected_output="; ".join(scenario["keywords"]),
                additional_metadata=metadata,
            )
        )

    evaluation_result = evaluate(
        test_cases=test_cases,
        metrics=[KeywordCoverageMetric(), RouteAccuracyMetric()],
        display_config=DisplayConfig(show_indicator=False, print_results=False, verbose_mode=False),
    )

    with open("agent_evaluation_scores.json", "w", encoding="utf-8") as handle:
        json.dump(evaluation_result.model_dump(), handle, indent=2)

    print("DeepEval assessment written to agent_evaluation_scores.json")


if __name__ == "__main__":
    main()

