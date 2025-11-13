from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from ninja import ModelSchema, Schema

from .models import Lead, LeadStatus, ProjectName, UnitType


class LeadSchema(ModelSchema):
    class Config:
        model = Lead
        model_fields = [
            "id",
            "crm_id",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "project_enquired",
            "unit_type",
            "status",
            "budget_min",
            "budget_max",
            "family_size",
            "location_preference",
            "purchase_motive",
            "financing_readiness",
            "profile_metadata",
            "last_conversation_date",
            "last_conversation_summary",
            "created_at",
            "updated_at",
        ]


class LeadFilterRequest(Schema):
    project_names: Optional[List[ProjectName]] = None
    budget_min: Optional[Decimal] = None
    budget_max: Optional[Decimal] = None
    unit_types: Optional[List[UnitType]] = None
    lead_status: Optional[LeadStatus] = None
    last_conversation_from: Optional[date] = None
    last_conversation_to: Optional[date] = None

    def active_filters(self) -> int:
        filters = [
            bool(self.project_names),
            self.budget_min is not None,
            self.budget_max is not None,
            bool(self.unit_types),
            self.lead_status is not None,
            self.last_conversation_from is not None,
            self.last_conversation_to is not None,
        ]
        return sum(filters)


class LeadShortlistResponse(Schema):
    count: int
    leads: List[LeadSchema]

