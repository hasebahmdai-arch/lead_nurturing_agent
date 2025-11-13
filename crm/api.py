from __future__ import annotations

from typing import List

from django.core.exceptions import ValidationError
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from .schemas import LeadFilterRequest, LeadSchema, LeadShortlistResponse
from .services import LeadShortlistService

router = Router(tags=["leads"])
auth = JWTAuth()


@router.post("/shortlist", response=LeadShortlistResponse, auth=auth)
def shortlist_leads(request, payload: LeadFilterRequest) -> LeadShortlistResponse:
    service = LeadShortlistService()
    try:
        result = service.shortlist(payload)
    except ValidationError as exc:
        raise HttpError(400, str(exc))

    leads = list(result.leads.select_related("user")[:200])
    serialized = [LeadSchema.from_orm(lead) for lead in leads]
    return LeadShortlistResponse(count=result.count, leads=serialized)

