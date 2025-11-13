from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, Literal, Optional, TypedDict
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from campaigns.models import Campaign, CampaignLead
from crm.models import Lead
from .rag import ProjectRAGService
from .t2sql import TextToSQLResult, VannaTextToSQLService


logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    query: str
    lead_id: int | None
    campaign_id: int | None
    route: Literal["t2sql", "rag"]
    response: Dict[str, object]


class QueryRouter:
    """Route questions between Text-to-SQL and RAG using an LLM classifier."""

    def __init__(self, llm: Optional[ChatGoogleGenerativeAI] = None) -> None:
        self.llm = llm or self._default_llm()

    def _default_llm(self) -> ChatGoogleGenerativeAI:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ImproperlyConfigured(
                "GOOGLE_API_KEY must be configured for Gemini access."
            )
        return ChatGoogleGenerativeAI(
            model=settings.AGENT_ROUTER_MODEL,
            temperature=0.0,
            google_api_key=api_key,
        )

    def decide(self, query: str) -> Literal["t2sql", "rag"]:
        prompt = (
            "You classify questions for a real-estate sales agent.\n"
            "Respond with only `T2SQL` if the question requires analytical metrics, SQL aggregates, numeric summaries, or CRM counts/averages.\n"
            "Respond with only `RAG` if the question requires brochure content, amenities, descriptions, copywriting, scheduling, or follow-up messaging.\n"
            f"Question: {query}\n"
            "Answer (T2SQL or RAG):"
        )
        try:
            response = self.llm.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            decision = content.strip().lower()
            if "sql" in decision:
                return "t2sql"
            if "rag" in decision:
                return "rag"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Router LLM failed (%s); falling back to heuristics.", exc)

        text = query.lower()
        sql_keywords = {
            "count",
            "number",
            "total",
            "average",
            "avg",
            "sum",
            "ratio",
            "metrics",
            "how many",
            "max",
            "min",
            "budget",
            "revenue",
        }
        if any(keyword in text for keyword in sql_keywords):
            return "t2sql"
        return "rag"


@dataclass
class DocumentAnswer:
    answer: str
    sources: list[str]
    route: Literal["rag"]


class DocumentAnswerTool:
    def __init__(self, *, rag_service: ProjectRAGService, llm: Optional[ChatGoogleGenerativeAI] = None) -> None:
        self.rag_service = rag_service
        self.llm = llm or self._default_llm()
        self.prompt = ChatPromptTemplate.from_template(
            """
You are an AI sales associate continuing a lead nurturing conversation for {project_name}.
Using the context below, answer the customer's question accurately and concisely.
Always close with a suggestion to schedule a viewing or call.

Lead context:
- Name: {lead_name}
- Preferences: {lead_preferences}
- Last conversation summary: {last_conversation_summary}

Customer question:
{question}

Brochure snippets:
{context}

Answer:
            """.strip()
        )

    def _default_llm(self) -> ChatGoogleGenerativeAI:
        from os import getenv

        api_key = getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ImproperlyConfigured("GOOGLE_API_KEY must be configured for Gemini access.")
        return ChatGoogleGenerativeAI(
            model=settings.DOCUMENT_QUERY_MODEL,
            temperature=0.2,
            google_api_key=api_key,
        )

    def answer(self, *, lead: Lead, campaign: Campaign, question: str) -> DocumentAnswer:
        retrieval = self.rag_service.get_documents(project_name=campaign.project_name, query=question)
        context = retrieval.as_context()
        prompt = self.prompt.format(
            project_name=campaign.project_name,
            lead_name=lead.first_name,
            lead_preferences=f"Unit type: {lead.unit_type}, Budget: {lead.budget_min}-{lead.budget_max}, Location: {lead.location_preference}",
            last_conversation_summary=lead.last_conversation_summary or "Unavailable",
            question=question,
            context=context or "No brochure context was found.",
        )
        response = self.llm.invoke(prompt)
        answer = response.content if hasattr(response, "content") else str(response)
        sources = [doc.metadata.get("source", "") for doc in retrieval.documents]
        return DocumentAnswer(answer=answer.strip(), sources=sources, route="rag")


class T2SQLAnswerFormatter:
    def format(self, question: str, result: TextToSQLResult) -> str:
        if not result.rows:
            return f"I could not find results for '{question}'."

        if len(result.rows) == 1 and len(result.rows[0]) == 1:
            key, value = next(iter(result.rows[0].items()))
            key_name = key.replace("_", " ")
            message = f"The {key_name} is {value}"
            question_lower = question.lower()
            qualifiers: list[str] = []
            if "connected" in question_lower:
                qualifiers.append("for connected leads")
            if "budget" in question_lower:
                qualifiers.append("for the requested budget")
            if "status" in question_lower and "connected" not in question_lower:
                qualifiers.append("for the requested status")
            if qualifiers:
                message += " " + " ".join(qualifiers)
            return message.rstrip() + "."

        lines = []
        for row in result.rows[:5]:
            parts = [f"{key.replace('_', ' ')}: {value}" for key, value in row.items()]
            lines.append(" • " + ", ".join(parts))

        summary = "\n".join(lines)
        if len(result.rows) > 5:
            summary += f"\nShowing first 5 of {len(result.rows)} records."
        return summary


class LeadNurtureAgent:
    def __init__(
        self,
        *,
        rag_service: ProjectRAGService,
        t2sql_service: VannaTextToSQLService,
        formatter: Optional[T2SQLAnswerFormatter] = None,
        llm: Optional[ChatGoogleGenerativeAI] = None,
    ) -> None:
        self.router = QueryRouter(llm=llm)
        self.rag_tool = DocumentAnswerTool(rag_service=rag_service, llm=llm)
        self.t2sql_service = t2sql_service
        self.formatter = formatter or T2SQLAnswerFormatter()

        graph = StateGraph(AgentState)
        graph.add_node("router", self._route)
        graph.add_node("t2sql", self._answer_sql)
        graph.add_node("rag", self._answer_rag)
        graph.set_entry_point("router")
        graph.add_conditional_edges(
            "router",
            self._next_step,
            {
                "t2sql": "t2sql",
                "rag": "rag",
            },
        )
        graph.add_edge("t2sql", END)
        graph.add_edge("rag", END)

        self.app = graph.compile(checkpointer=MemorySaver())

    def _route(self, state: AgentState) -> AgentState:
        route = self.router.decide(state["query"])
        return {"route": route}

    def _next_step(self, state: AgentState) -> Literal["t2sql", "rag"]:
        return state["route"]

    def _answer_sql(self, state: AgentState) -> AgentState:
        lead = Lead.objects.get(pk=state["lead_id"]) if state.get("lead_id") else None
        campaign = Campaign.objects.get(pk=state["campaign_id"]) if state.get("campaign_id") else None
        result = self.t2sql_service.answer(state["query"])
        message = self.formatter.format(state["query"], result)
        logger.info(
            "LeadNurtureAgent route=t2sql lead_id=%s campaign_id=%s row_count=%s",
            state.get("lead_id"),
            state.get("campaign_id"),
            len(result.rows),
        )
        response = {
            "route": "t2sql",
            "sql": result.sql,
            "rows": result.rows,
            "explanation": result.explanation,
            "message": message,
        }
        return {"response": response}

    def _answer_rag(self, state: AgentState) -> AgentState:
        lead = Lead.objects.get(pk=state["lead_id"]) if state.get("lead_id") else None
        campaign = Campaign.objects.get(pk=state["campaign_id"]) if state.get("campaign_id") else None
        if not lead or not campaign:
            raise ImproperlyConfigured("Lead and campaign are required for RAG responses.")
        answer = self.rag_tool.answer(lead=lead, campaign=campaign, question=state["query"])
        logger.info(
            "LeadNurtureAgent route=rag lead_id=%s campaign_id=%s sources=%s",
            state.get("lead_id"),
            state.get("campaign_id"),
            answer.sources,
        )
        response = {
            "route": "rag",
            "answer": answer.answer,
            "sources": answer.sources,
        }
        return {"response": response}

    def run(self, *, query: str, campaign_lead: CampaignLead, thread_id: str) -> Dict[str, object]:
        state: AgentState = {
            "query": query,
            "lead_id": campaign_lead.lead_id,
            "campaign_id": campaign_lead.campaign_id,
        }
        result = self.app.invoke(state, config={"thread_id": thread_id})
        return result["response"]

