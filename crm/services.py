from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.core.exceptions import ValidationError
from django.db.models import QuerySet

from .models import Lead
from .schemas import LeadFilterRequest


@dataclass
class LeadShortlistResult:
    leads: QuerySet
    criteria: LeadFilterRequest

    @property
    def count(self) -> int:
        return self.leads.count()


class LeadShortlistService:
    minimum_filters = 2

    def shortlist(self, criteria: LeadFilterRequest) -> LeadShortlistResult:
        if criteria.active_filters() < self.minimum_filters:
            raise ValidationError(
                f"Please select at least {self.minimum_filters} filter fields before shortlisting leads."
            )

        queryset = Lead.objects.all()
        queryset = queryset.shortlist(
            project_names=criteria.project_names,
            unit_types=criteria.unit_types,
            lead_status=criteria.lead_status,
            last_conversation_from=criteria.last_conversation_from,
            last_conversation_to=criteria.last_conversation_to,
            budget_min=criteria.budget_min,
            budget_max=criteria.budget_max,
        )

        return LeadShortlistResult(leads=queryset, criteria=criteria)


def serialize_leads(leads: Iterable[Lead]) -> list[dict]:
    return [
        {
            "id": lead.id,
            "crm_id": lead.crm_id,
            "full_name": lead.full_name,
            "email": lead.email,
            "phone_number": lead.phone_number,
            "project_enquired": lead.project_enquired,
            "unit_type": lead.unit_type,
            "status": lead.status,
            "budget_min": lead.budget_min,
            "budget_max": lead.budget_max,
            "last_conversation_date": lead.last_conversation_date,
            "last_conversation_summary": lead.last_conversation_summary,
        }
        for lead in leads
    ]

