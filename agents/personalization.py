from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from campaigns.models import Campaign
from crm.models import Lead
from .rag import ProjectRAGService


@dataclass
class PersonalizedMessage:
    body: str
    sources: list[str]
    context_snippet: str


class PersonalizedMessageGenerator:
    def __init__(
        self,
        *,
        rag_service: ProjectRAGService,
        llm: Optional[ChatGoogleGenerativeAI] = None,
    ) -> None:
        self.rag_service = rag_service
        self.llm = llm or self._default_llm()
        self.prompt = ChatPromptTemplate.from_template(
            """
You are an AI property sales assistant tasked with nurturing leads.
Compose a hyper-personalized {channel} message. Strictly follow the rules:
- Use the lead's first name in the greeting.
- Acknowledge their previous enquiry and last conversation summary.
- Highlight the project features that align with the lead's preferences, using the provided brochure context.
- If a sales offer is provided (Offer details != "[omit offer]"), include it immediately before the call to action.
- Close with an assertive call to action encouraging the lead to schedule a property viewing or call.

Lead profile:
- Name: {lead_name}
- Family size: {family_size}
- Budget range: {budget_range}
- Unit preference: {unit_type}
- Location preference: {location_preference}
- Purchase motive: {purchase_motive}
- Financing readiness: {financing_readiness}
- Additional notes: {additional_notes}
- Last conversation date: {last_conversation_date}
- Last conversation summary: {last_conversation_summary}

Campaign:
- Project name: {project_name}
- Offer details: {offer_details}
- Message channel: {channel}

Brochure context:
{project_context}

Respond with the final message only.
            """.strip()
        )

    def _default_llm(self) -> ChatGoogleGenerativeAI:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ImproperlyConfigured("GOOGLE_API_KEY must be configured for Gemini access.")
        return ChatGoogleGenerativeAI(
            model=settings.PERSONALIZATION_MODEL,
            temperature=0.4,
            google_api_key=api_key,
        )

    def generate(self, *, campaign: Campaign, lead: Lead, offer_details: Optional[str]) -> PersonalizedMessage:
        rag_result = self.rag_service.get_documents(
            project_name=campaign.project_name,
            query=f"Key selling points for {campaign.project_name} relevant to {lead.unit_type} and budget {lead.budget_min}-{lead.budget_max}",
        )
        context_snippet = rag_result.as_context()
        sources = [doc.metadata.get("source", "") for doc in rag_result.documents]

        budget_range = " | ".join(
            str(value) for value in (lead.budget_min, lead.budget_max) if value is not None
        ) or "Not specified"

        rendered_prompt = self.prompt.format(
            channel=campaign.message_channel.upper(),
            lead_name=lead.first_name,
            family_size=lead.family_size or "Not specified",
            budget_range=budget_range,
            unit_type=lead.unit_type,
            location_preference=lead.location_preference or "Not specified",
            purchase_motive=lead.purchase_motive or "Not specified",
            financing_readiness=lead.financing_readiness or "Not specified",
            additional_notes=lead.profile_metadata or "None recorded",
            last_conversation_date=lead.last_conversation_date or "Unavailable",
            last_conversation_summary=lead.last_conversation_summary or "Unavailable",
            project_name=campaign.project_name,
            offer_details=offer_details or "[omit offer]",
            project_context=context_snippet or "No brochure information was available.",
        )
        response = self.llm.invoke(rendered_prompt)
        message_text = response.content if hasattr(response, "content") else str(response)
        return PersonalizedMessage(body=message_text.strip(), sources=sources, context_snippet=context_snippet)

